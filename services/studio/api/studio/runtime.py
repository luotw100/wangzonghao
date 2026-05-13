"""Studio worker runtime.

Three scanners run side-by-side:
- DistillScanner: picks up DistillJob rows in 'pending' state and runs the
  rolling fold pipeline.
- ReplyScanner: picks up Contacts with pending_reply=True, gates them
  through studio.reply._decide(), and (if all gates pass + quiet-period
  elapsed) calls the LLM and queues outbound messages.
- BridgeOfflineScanner: marks bridges as offline when last_seen_at exceeds
  the heartbeat grace period.

All scanners are simple poll loops; concurrency is bounded by
in-flight task dictionaries to avoid double-processing the same row.

Studio does not hold any long-lived platform connection. Live message I/O
is the Bridge daemon's job; runtime only reads/writes studio.db.
"""

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import timedelta, timezone
from typing import Any, Dict, Optional

from studio.clients import ProviderClient
from studio.db import SessionLocal, utc_now
from studio.distill.pipeline import run_distill
from studio.enums import BridgeStatus, DistillJobStatus
from studio.models import Bridge, DistillJob
from studio.reply import list_pending_contact_ids, maybe_reply

logger = logging.getLogger(__name__)

BRIDGE_OFFLINE_AFTER = timedelta(seconds=45)


@dataclass(frozen=True)
class RuntimeOptions:
    request_timeout: float


class StudioRuntime:
    def __init__(self, options: RuntimeOptions):
        self.options = options
        self._distill_scanner_task: Optional[asyncio.Task[Any]] = None
        self._distill_tasks: Dict[str, asyncio.Task[Any]] = {}
        self._reply_scanner_task: Optional[asyncio.Task[Any]] = None
        self._reply_tasks: Dict[str, asyncio.Task[Any]] = {}
        self._reply_provider: Optional[ProviderClient] = None
        self._bridge_offline_task: Optional[asyncio.Task[Any]] = None

    async def start(self):
        loop = asyncio.get_running_loop()
        self._reply_provider = ProviderClient(request_timeout=self.options.request_timeout)
        self._distill_scanner_task = loop.create_task(
            self._distill_scanner_loop(), name="distill-scanner"
        )
        self._reply_scanner_task = loop.create_task(
            self._reply_scanner_loop(), name="reply-scanner"
        )
        self._bridge_offline_task = loop.create_task(
            self._bridge_offline_scanner_loop(), name="bridge-offline-scanner"
        )

    async def stop(self):
        for t in (self._distill_scanner_task, self._reply_scanner_task, self._bridge_offline_task):
            if t:
                t.cancel()
                with suppress(asyncio.CancelledError):
                    await t
        in_flight = list(self._distill_tasks.values()) + list(self._reply_tasks.values())
        for task in in_flight:
            task.cancel()
        for task in in_flight:
            with suppress(asyncio.CancelledError):
                await task
        self._distill_tasks.clear()
        self._reply_tasks.clear()
        if self._reply_provider:
            await self._reply_provider.close()

    # --- Distill --------------------------------------------------------

    async def _distill_scanner_loop(self):
        while True:
            try:
                db = SessionLocal()
                try:
                    pending = (
                        db.query(DistillJob)
                        .filter(DistillJob.status == DistillJobStatus.PENDING)
                        .order_by(DistillJob.created_at.asc())
                        .all()
                    )
                    pending_ids = [
                        (j.id, j.source_inbox_id, j.target_persona_id, j.provider_config_id)
                        for j in pending
                    ]
                finally:
                    db.close()

                for jid in list(self._distill_tasks.keys()):
                    if self._distill_tasks[jid].done():
                        del self._distill_tasks[jid]

                for job_id, source_inbox_id, target_persona_id, provider_config_id in pending_ids:
                    if job_id in self._distill_tasks:
                        continue
                    self._distill_tasks[job_id] = asyncio.get_running_loop().create_task(
                        self._run_distill_job(
                            job_id, source_inbox_id, target_persona_id, provider_config_id
                        ),
                        name=f"distill-{job_id}",
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Distill scanner error: %s", exc)

            await asyncio.sleep(5)

    async def _run_distill_job(
        self,
        job_id: str,
        source_inbox_id: str,
        target_persona_id: str,
        provider_config_id: str,
    ):
        db = SessionLocal()
        try:
            job = db.query(DistillJob).filter(DistillJob.id == job_id).first()
            if not job or job.status != DistillJobStatus.PENDING:
                return
            job.status = DistillJobStatus.RUNNING
            job.started_at = utc_now()
            db.commit()
        finally:
            db.close()

        def progress_cb(state: Dict[str, int]):
            d = SessionLocal()
            try:
                j = d.query(DistillJob).filter(DistillJob.id == job_id).first()
                if j:
                    j.progress = state
                    d.commit()
            finally:
                d.close()

        try:
            await run_distill(
                source_inbox_id=source_inbox_id,
                target_persona_id=target_persona_id,
                provider_config_id=provider_config_id,
                request_timeout=self.options.request_timeout,
                progress_cb=progress_cb,
            )
        except Exception as exc:
            logger.error("Distill job %s failed: %s", job_id, exc)
            db = SessionLocal()
            try:
                j = db.query(DistillJob).filter(DistillJob.id == job_id).first()
                if j:
                    j.status = DistillJobStatus.FAILED
                    j.error_message = str(exc)
                    j.finished_at = utc_now()
                    db.commit()
            finally:
                db.close()
            return

        db = SessionLocal()
        try:
            j = db.query(DistillJob).filter(DistillJob.id == job_id).first()
            if j:
                j.status = DistillJobStatus.DONE
                j.finished_at = utc_now()
                db.commit()
        finally:
            db.close()

    # --- Reply ----------------------------------------------------------

    async def _reply_scanner_loop(self):
        while True:
            try:
                pending = list_pending_contact_ids()
                # Reap finished tasks
                for cid in list(self._reply_tasks.keys()):
                    if self._reply_tasks[cid].done():
                        del self._reply_tasks[cid]
                for cid in pending:
                    if cid in self._reply_tasks:
                        continue
                    self._reply_tasks[cid] = asyncio.get_running_loop().create_task(
                        self._run_reply(cid), name=f"reply-{cid}"
                    )
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("Reply scanner error: %s", exc)

            await asyncio.sleep(2)

    async def _run_reply(self, contact_id: str):
        try:
            assert self._reply_provider is not None
            status = await maybe_reply(self._reply_provider, contact_id)
            logger.info("Reply [%s] %s", contact_id, status)
        except Exception as exc:
            logger.error("Reply task for %s crashed: %s", contact_id, exc)

    # --- Bridge Offline --------------------------------------------------

    async def _bridge_offline_scanner_loop(self):
        while True:
            try:
                cutoff = utc_now() - BRIDGE_OFFLINE_AFTER
                db = SessionLocal()
                try:
                    expired = (
                        db.query(Bridge)
                        .filter(
                            Bridge.status == BridgeStatus.ONLINE,
                            Bridge.last_seen_at < cutoff,
                        )
                        .all()
                    )
                    if expired:
                        for b in expired:
                            b.status = BridgeStatus.OFFLINE
                        db.commit()
                        logger.info("BridgeOfflineScanner: marked %d bridges offline", len(expired))
                finally:
                    db.close()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.error("BridgeOfflineScanner error: %s", exc)

            await asyncio.sleep(30)
