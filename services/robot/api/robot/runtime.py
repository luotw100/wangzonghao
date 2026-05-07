"""Robot worker runtime — distill scanner only.

The session-loop / chat-poll path is intentionally absent: live reply is the
responsibility of the future B (local-client bridge), not Robot. Robot only
runs distillation jobs in the background.
"""

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Dict, Optional

from robot.db import SessionLocal, utc_now
from robot.distill.pipeline import run_distill
from robot.models import DistillJob

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RuntimeOptions:
    request_timeout: float


class RobotRuntime:
    def __init__(self, options: RuntimeOptions):
        self.options = options
        self._distill_scanner_task: Optional[asyncio.Task[Any]] = None
        self._distill_tasks: Dict[str, asyncio.Task[Any]] = {}

    async def start(self):
        loop = asyncio.get_running_loop()
        self._distill_scanner_task = loop.create_task(
            self._distill_scanner_loop(), name="distill-scanner"
        )

    async def stop(self):
        if self._distill_scanner_task:
            self._distill_scanner_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._distill_scanner_task
        for task in list(self._distill_tasks.values()):
            task.cancel()
        for task in list(self._distill_tasks.values()):
            with suppress(asyncio.CancelledError):
                await task
        self._distill_tasks.clear()

    async def _distill_scanner_loop(self):
        while True:
            try:
                db = SessionLocal()
                try:
                    pending = (
                        db.query(DistillJob)
                        .filter(DistillJob.status == "pending")
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
            if not job or job.status != "pending":
                return
            job.status = "running"
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
                    j.status = "failed"
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
                j.status = "done"
                j.finished_at = utc_now()
                db.commit()
        finally:
            db.close()
