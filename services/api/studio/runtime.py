"""Studio worker runtime.

Two scanners run side-by-side:
- DistillScanner: picks up DistillJob rows in 'pending' state and runs the
  rolling fold pipeline.
- ReplyScanner: derives Conversations that need an autoreply (latest
  message from counterpart, newer than last_reply_round_at), gates them
  through studio.reply._decide(), and (if all gates pass + quiet-period
  elapsed) calls the LLM and queues outbound messages.

Bridge online/offline is derived from last_seen_at at read time; no
scanner needed to flip a cached status.
"""

import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from typing import Any, Dict, Optional

from studio.clients import ProviderClient
from studio.db import SessionLocal, utc_now
from studio.distill.pipeline import run_distill
from studio.enums import DistillJobStatus
from studio.models import DistillJob
from studio.reply import list_pending_conversation_ids, maybe_reply

logger = logging.getLogger(__name__)


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

    async def start(self):
        loop = asyncio.get_running_loop()
        self._reply_provider = ProviderClient(request_timeout=self.options.request_timeout)
        self._distill_scanner_task = loop.create_task(
            self._distill_scanner_loop(), name="distill-scanner"
        )
        self._reply_scanner_task = loop.create_task(
            self._reply_scanner_loop(), name="reply-scanner"
        )

    async def stop(self):
        for t in (self._distill_scanner_task, self._reply_scanner_task):
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
        """蒸馏任务扫描器（每 5s 扫一次 DB）。

        吃：DistillJob 表中 status=pending 的行（按 created_at asc 排序，先提交先执行）
        吐：为每个可调度的 pending job 创建一个 asyncio Task（_run_distill_job），
            并维护 busy_conversations / busy_personas 集合防止同一会话或人设并发蒸馏。

        调度规则：
          - 已有 running 的 job 占用了相同会话或相同目标人设时，pending job 跳过等下轮。
          - 每次扫描后 done 的 Task 从 _distill_tasks 字典中移除。
        """
        while True:
            try:
                db = SessionLocal()
                try:
                    running = (
                        db.query(DistillJob)
                        .filter(DistillJob.status == DistillJobStatus.RUNNING)
                        .all()
                    )
                    pending = (
                        db.query(DistillJob)
                        .filter(DistillJob.status == DistillJobStatus.PENDING)
                        .order_by(DistillJob.created_at.asc())
                        .all()
                    )
                    busy_conversations: set[str] = set()
                    busy_personas: set[str] = set()
                    for j in running:
                        busy_conversations.update(j.conversation_ids or [])
                        if j.target_persona_id:
                            busy_personas.add(j.target_persona_id)
                    pending_specs = [
                        (j.id, list(j.conversation_ids or []), j.target_persona_id, j.provider_config_id)
                        for j in pending
                    ]
                finally:
                    db.close()

                for jid in list(self._distill_tasks.keys()):
                    if self._distill_tasks[jid].done():
                        del self._distill_tasks[jid]

                for job_id, conv_ids, target_persona_id, provider_config_id in pending_specs:
                    if job_id in self._distill_tasks:
                        continue
                    if any(c in busy_conversations for c in conv_ids):
                        continue
                    if target_persona_id and target_persona_id in busy_personas:
                        continue
                    busy_conversations.update(conv_ids)
                    if target_persona_id:
                        busy_personas.add(target_persona_id)
                    self._distill_tasks[job_id] = asyncio.get_running_loop().create_task(
                        self._run_distill_job(
                            job_id, conv_ids, target_persona_id, provider_config_id
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
        conversation_ids: list[str],
        target_persona_id: Optional[str],
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
                conversation_ids=conversation_ids,
                target_persona_id=target_persona_id,
                provider_config_id=provider_config_id,
                request_timeout=self.options.request_timeout,
                distill_job_id=job_id,
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
        """自动回复扫描器（每 2s 扫一次 DB）。

        吃：list_pending_conversation_ids() — 查找需要触发 LLM 回复的会话 ID 列表。
            触发条件（由 reply.list_pending_conversation_ids 内部判断）：
              1. takeover=True + reply_policy=autoreply + persona_id 非空
              2. 最新消息来自对方（sender_id 非 NULL）
              3. 最新消息时间 > last_reply_round_at（还没有回过这一轮）
        吐：为每个待回复的 conversation_id 创建一个 asyncio Task（_run_reply），
            Task 内调用 maybe_reply() → ProviderClient.complete_chat() → 写 OutboundMessage。
            同一会话同时只有一个 reply Task（已在 _reply_tasks 中的跳过）。
        """
        while True:
            try:
                pending = list_pending_conversation_ids()
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

    async def _run_reply(self, conversation_id: str):
        try:
            assert self._reply_provider is not None
            status = await maybe_reply(self._reply_provider, conversation_id)
            logger.info("Reply [%s] %s", conversation_id, status)
        except Exception as exc:
            logger.error("Reply task for %s crashed: %s", conversation_id, exc)
