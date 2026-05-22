"""Bridge runtime — Supervisor + ChannelWorker + 3 global actors.

Design: sqlite is the only source of truth for cross-actor coordination.
No notifies, no queues — every actor just polls its own input on a fixed
cadence and writes its outputs to sqlite (or to a single atomic snapshot
in the case of the takeover set). This trades sub-second responsiveness
for one fewer invariant to maintain: there is no "did the notify arrive
before/after the row landed" race to think about.

Layout::

    Supervisor                  one daemon-level brain
    ├─ ChannelWorker × N        one per Channel row; owns the Adapter,
    │                           inbox registration, conversation
    │                           directory diff push, and fetch_new loop.
    │                           Tick is driven by the supervisor's
    │                           scheduler thread — workers never sleep
    │                           themselves.
    ├─ Scheduler   1 thread     calls worker.tick() every PRODUCER_S
    ├─ UploadActor 1 thread     store.get_unsent(takeovers) →
    │                           studio.push_incoming → store.mark_sent
    ├─ TakeoverActor 1 thread   studio.get_takeovers → atomic-replace
    │                           shared `takeovers` snapshot
    ├─ OutboundActor 1 thread   long-poll studio.get_outbound → worker.send
    └─ HeartbeatActor 1 thread  studio.heartbeat; 401 → auth_error + stop

Worker state machine::

    CONNECTING → ONLINE              build adapter + register inbox ok
    CONNECTING → NEEDS_LOGIN         build/identity raised Unauthorized
    CONNECTING → BACKOFF             transient/unknown error
    BACKOFF    → CONNECTING          after BACKOFF_S elapsed
    ONLINE     → NEEDS_LOGIN         adapter Unauthorized during poll
    ONLINE     → BACKOFF             transient error during poll
    *          → REMOVED             channel deleted out from under us
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import adapters
from .events import Events
from .http import Unauthorized as HttpUnauthorized
from .store import Store
from .studio_client import StudioClient

# Poll cadences (seconds). All actor sleeps go through stop_event.wait()
# so they are torn down promptly on /quit.
PRODUCER_S = 2          # how often each ChannelWorker.tick() runs
UPLOAD_S = 1            # UploadActor sweep interval
TAKEOVERS_S = 10        # /takeovers refresh
HEARTBEAT_S = 15        # /heartbeat
OUTBOUND_TIMEOUT_S = 30 # long-poll timeout for /outbound
BACKOFF_S = 5           # ChannelWorker retry delay after a transient
UPLOAD_BATCH = 50
INFLIGHT_TTL_S = 60     # outbound dedup window


# ---------------------------------------------------------------------------
# Conversation directory signature
# ---------------------------------------------------------------------------

def _conv_signature(convs: list[adapters.Conversation]) -> tuple:
    """Stable hashable summary used to skip redundant /conversations pushes.

    Held in memory only — on daemon restart we push once and resync.
    """
    return tuple(
        sorted(
            (
                c.id,
                c.kind,
                c.display_name,
                tuple(sorted((p["platform_id"], p["display_name"]) for p in c.peers)),
            )
            for c in convs
        )
    )


def _to_push_conversations(convs: list[adapters.Conversation]) -> list[dict]:
    return [
        {
            "platform_conversation_id": c.id,
            "kind": c.kind,
            "display_name": c.display_name,
            "members": [
                {"peer_platform_id": p["platform_id"], "display_name": p["display_name"]}
                for p in c.peers
            ],
        }
        for c in convs
    ]


# ---------------------------------------------------------------------------
# ChannelWorker
# ---------------------------------------------------------------------------

CONNECTING = "connecting"
ONLINE = "online"
NEEDS_LOGIN = "needs_login"
BACKOFF = "backoff"
REMOVED = "removed"


@dataclass
class _WorkerSnapshot:
    """Read-only view the supervisor exposes via Events.set_state."""

    channel_id: int
    platform: str
    state: str
    platform_self_id: str | None
    inbox_id: str | None
    conv_count: int
    last_error: str | None


class ChannelWorker:
    """One bound channel. Owns its Adapter; everything else (cursors,
    messages, inbox cache) lives in the shared Store.

    `tick()` is called by the supervisor's scheduler thread. It performs
    one bounded step appropriate to the current state and returns; the
    worker never sleeps internally.
    """

    def __init__(
        self,
        channel_id: int,
        platform: str,
        credential: dict,
        store: Store,
        studio: StudioClient,
        events: Events,
    ) -> None:
        self.channel_id = channel_id
        self.platform = platform
        self._credential = credential
        self._store = store
        self._studio = studio
        self._events = events

        self.state: str = CONNECTING
        self.adapter: adapters.Adapter | None = None
        self.inbox: dict | None = None     # {id, platform, platform_self_id, display_name}
        self.platform_self_id: str | None = None
        self.last_error: str | None = None
        self._conv_signature: tuple | None = None
        self._conv_count: int = 0
        self._backoff_until: float = 0.0

    # ---- public api ---------------------------------------------------

    def snapshot(self) -> _WorkerSnapshot:
        return _WorkerSnapshot(
            channel_id=self.channel_id,
            platform=self.platform,
            state=self.state,
            platform_self_id=self.platform_self_id,
            inbox_id=(self.inbox or {}).get("id"),
            conv_count=self._conv_count,
            last_error=self.last_error,
        )

    def tick(self) -> None:
        """One bounded step. Called by the supervisor's scheduler."""
        try:
            if self.state == NEEDS_LOGIN or self.state == REMOVED:
                return
            if self.state == BACKOFF:
                if time.monotonic() < self._backoff_until:
                    return
                self.state = CONNECTING
            if self.state == CONNECTING:
                self._connect()
                return
            if self.state == ONLINE:
                self._poll()
        except adapters.Unauthorized:
            self._log("err", "credential 失效 — 需要 /channel relogin")
            self.last_error = "credential 失效"
            self.adapter = None
            self.state = NEEDS_LOGIN
        except adapters.TransientError as exc:
            self._log("warn", f"{exc} — 退避 {BACKOFF_S}s")
            self.last_error = str(exc)
            self._enter_backoff()
        except HttpUnauthorized:
            # Studio side 401. Surfaced by HeartbeatActor as the canonical
            # auth error; per-worker we just back off so this loop doesn't
            # spin while the daemon tears down.
            self._enter_backoff()
        except Exception as exc:
            self._log("err", f"unexpected {type(exc).__name__}: {exc}")
            self.last_error = f"{type(exc).__name__}: {exc}"
            self._enter_backoff()

    def mark_removed(self) -> None:
        self.state = REMOVED
        self.adapter = None

    # ---- internals ----------------------------------------------------

    def _enter_backoff(self) -> None:
        self.state = BACKOFF
        self._backoff_until = time.monotonic() + BACKOFF_S

    def _log(self, level: str, msg: str) -> None:
        self._events.log(f"ch{self.channel_id}", level, f"{self.platform}: {msg}")

    def _connect(self) -> None:
        factory = adapters.get(self.platform)
        adapter = factory.build(self._credential)
        self_id = adapter.platform_self_id
        self_display = adapter.platform_self_display_name
        inboxes = self._studio.register_inboxes(
            [{
                "platform": self.platform,
                "platform_self_id": self_id,
                "display_name": self_display,
            }]
        )
        inbox = next(
            (i for i in inboxes
             if i["platform"] == self.platform and i["platform_self_id"] == self_id),
            None,
        )
        if inbox is None:
            raise adapters.TransientError(
                "Studio 未返回匹配的 inbox（稍后重试）"
            )
        self._store.set_channel_inbox(self.channel_id, inbox["id"])
        self.adapter = adapter
        self.inbox = inbox
        self.platform_self_id = self_id
        self.last_error = None
        self.state = ONLINE
        self._log("ok", f"online · self_id={self_id} · inbox={inbox['id']}")

    def _poll(self) -> None:
        assert self.adapter is not None and self.inbox is not None
        inbox_id = self.inbox["id"]
        convs = self.adapter.list_conversations()
        self._conv_count = len(convs)

        sig = _conv_signature(convs)
        if sig != self._conv_signature:
            self._studio.push_conversations(
                inbox_id, _to_push_conversations(convs)
            )
            self._conv_signature = sig
            self._log("ok", f"pushed {len(convs)} conversations (diff)")

        for c in convs:
            since = self._store.get_cursor(inbox_id, c.id)
            events = self.adapter.fetch_new(c.id, since)
            if not events:
                continue
            self._store.ingest(
                inbox_id,
                c.id,
                [
                    {
                        "client_id": e.client_id,
                        "sender_id": e.sender_id,
                        "sent_at": e.sent_at,
                        "msg_type": e.msg_type,
                        "content": e.content,
                    }
                    for e in events
                ],
                events[-1].cursor,
            )

    def send_outbound(self, item: dict) -> None:
        """Called by OutboundActor. Raises only adapter errors; the
        actor logs them but does not change worker state — a transient
        send failure is per-message, not per-channel.
        """
        if self.state != ONLINE or self.adapter is None:
            raise adapters.TransientError("worker not online")
        payload = adapters.OutboundPayload(
            msg_type=item["msg_type"], content=item["content"]
        )
        self.adapter.send(item["platform_conversation_id"], payload)


# ---------------------------------------------------------------------------
# Supervisor / BridgeRuntime
# ---------------------------------------------------------------------------

class BridgeRuntime:
    """Daemon-level supervisor. One instance per active Studio account.

    Public surface (kept compatible with commands.py):
      start() / stop() / is_running()
    """

    def __init__(
        self,
        studio: StudioClient,
        store: Store,
        events: Events,
        base_info: Callable[[], dict],
        on_auth_error: Callable[[], None],
    ) -> None:
        self._studio = studio
        self._store = store
        self._events = events
        self._base_info = base_info
        self._on_auth_error = on_auth_error

        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []
        self._lock = threading.Lock()
        self._workers: dict[int, ChannelWorker] = {}

        # Atomic-replaced snapshot of takeovers; readers just take the
        # reference, no lock needed. Format: frozenset of
        # "inbox_id|platform_conversation_id" strings.
        self._takeovers: frozenset[str] = frozenset()

        # Outbound dedup: {item_id: dispatched_at_monotonic}. Pruned
        # each long-poll; entries older than INFLIGHT_TTL_S are gone.
        self._inflight: dict[int, float] = {}
        self._inflight_lock = threading.Lock()

        self._last_error: str | None = None
        self._status: str = "idle"

    # ---- lifecycle ----------------------------------------------------

    def start(self) -> None:
        if self._threads:
            return
        self._stop.clear()
        self._set_status("connecting")
        # Spawn workers up-front (one per stored channel). Each starts
        # in CONNECTING and gets its first tick from the scheduler.
        for ch in self._store.channels():
            self._workers[ch.id] = ChannelWorker(
                ch.id, ch.platform, ch.credential,
                self._store, self._studio, self._events,
            )
        if not self._workers:
            self._last_error = "尚未添加 channel"
            self._set_status("idle")
            self._push_state()
            return

        self._push_state()
        self._spawn(self._scheduler_loop, "scheduler")
        self._spawn(self._upload_loop, "upload")
        self._spawn(self._takeover_loop, "takeover")
        self._spawn(self._outbound_loop, "outbound")
        self._spawn(self._heartbeat_loop, "heartbeat")

    def stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        for t in self._threads:
            if t is not threading.current_thread():
                t.join(timeout=2)
        self._threads.clear()
        with self._lock:
            for w in self._workers.values():
                w.mark_removed()
            self._workers.clear()
        self._set_status("idle")
        self._push_state()
        self._log("core", "info", "daemon stopped")

    def is_running(self) -> bool:
        return bool(self._threads) and not self._stop.is_set()

    # ---- helpers ------------------------------------------------------

    def _spawn(self, target, name: str) -> None:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self._threads.append(t)

    def _sleep(self, secs: float) -> bool:
        """Returns True if stop was requested during the sleep."""
        return self._stop.wait(timeout=secs)

    def _log(self, src: str, level: str, msg: str) -> None:
        self._events.log(src, level, msg)

    def _set_status(self, s: str) -> None:
        self._status = s

    def _push_state(self) -> None:
        with self._lock:
            snaps = [w.snapshot() for w in self._workers.values()]
        any_online = any(s.state == ONLINE for s in snaps)
        # Derived top-line status. Idle/connecting/error are set
        # explicitly elsewhere; otherwise we read from the workers.
        if self._status not in {"idle", "error401"}:
            if any_online:
                self._status = "online"
            elif all(s.state == NEEDS_LOGIN for s in snaps) and snaps:
                self._status = "needs_login"
            elif snaps:
                self._status = "degraded"
        since = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        self._events.set_state(
            {
                **self._base_info(),
                "status": self._status,
                "channels": [
                    {
                        "channel_id": s.channel_id,
                        "platform": s.platform,
                        "platform_self_id": s.platform_self_id,
                        "inbox_id": s.inbox_id,
                        "state": s.state,
                        "online": s.state == ONLINE,
                        "conv_count": s.conv_count,
                        "last_error": s.last_error,
                    }
                    for s in snaps
                ],
                "in_count_5m": self._store.count_recent_incoming(since),
                "outbound_pending": self._store.count_unsent(),
                "last_error": self._last_error,
            }
        )

    def _auth_error(self, msg: str) -> None:
        self._last_error = msg
        self._set_status("error401")
        try:
            self._on_auth_error()
        except Exception as exc:
            self._log("core", "warn", f"on_auth_error raised: {exc}")
        # Schedule a teardown from a fresh thread so the calling actor
        # can return cleanly before stop() joins it.
        threading.Thread(target=self.stop, daemon=True).start()

    # ---- scheduler ----------------------------------------------------

    def _scheduler_loop(self) -> None:
        while not self._stop.is_set():
            with self._lock:
                workers = list(self._workers.values())
            for w in workers:
                if self._stop.is_set():
                    return
                w.tick()
            self._push_state()
            if self._sleep(PRODUCER_S):
                return

    # ---- upload actor -------------------------------------------------

    def _upload_loop(self) -> None:
        while not self._stop.is_set():
            try:
                self._upload_once()
            except HttpUnauthorized:
                # Heartbeat will surface as the canonical 401. Just stop.
                return
            except Exception as exc:
                self._log("upload", "warn", f"sweep failed: {exc}")
            if self._sleep(UPLOAD_S):
                return

    def _upload_once(self) -> None:
        takeovers = self._takeovers  # atomic read of immutable snapshot
        if not takeovers:
            return
        rows = self._store.get_unsent(UPLOAD_BATCH, takeovers)
        if not rows:
            return
        with self._lock:
            known_inboxes = {
                w.inbox["id"] for w in self._workers.values()
                if w.inbox is not None
            }
        # Rows whose inbox isn't currently registered (worker still
        # connecting, or channel removed): just skip. mark_sent would lie
        # ("delivered to Studio") and lose data during the startup race
        # where the upload sweep beats the worker's first /inboxes call.
        batch = [r for r in rows if r.inbox_id in known_inboxes]
        if not batch:
            return
        self._studio.push_incoming(
            [
                {
                    "inbox_id": r.inbox_id,
                    "platform_conversation_id": r.conversation_id,
                    "client_id": r.client_id,
                    "sender_id": r.sender_id,
                    "msg_type": r.msg_type,
                    "content": r.content,
                    "sent_at": r.sent_at,
                }
                for r in batch
            ]
        )
        self._store.mark_sent([r.id for r in batch])

    # ---- takeover actor ----------------------------------------------

    def _takeover_loop(self) -> None:
        while not self._stop.is_set():
            try:
                items = self._studio.get_takeovers()
                self._takeovers = frozenset(
                    f"{t['inbox_id']}|{t['platform_conversation_id']}"
                    for t in items
                )
            except HttpUnauthorized:
                return
            except Exception as exc:
                self._log("takeover", "warn", f"refresh failed: {exc}")
            if self._sleep(TAKEOVERS_S):
                return

    # ---- outbound actor ----------------------------------------------

    def _outbound_loop(self) -> None:
        while not self._stop.is_set():
            try:
                items = self._studio.get_outbound(OUTBOUND_TIMEOUT_S)
            except HttpUnauthorized:
                return
            except Exception as exc:
                self._log("outbound", "warn", f"poll error: {exc}")
                if self._sleep(2):
                    return
                continue
            self._prune_inflight()
            for item in items:
                if self._stop.is_set():
                    return
                if self._mark_inflight(item["id"]):
                    self._dispatch_outbound(item)

    def _prune_inflight(self) -> None:
        now = time.monotonic()
        with self._inflight_lock:
            stale = [k for k, t in self._inflight.items() if now - t > INFLIGHT_TTL_S]
            for k in stale:
                del self._inflight[k]

    def _mark_inflight(self, item_id: int) -> bool:
        """Returns True if this is a new id we should dispatch."""
        now = time.monotonic()
        with self._inflight_lock:
            if item_id in self._inflight:
                return False
            self._inflight[item_id] = now
            return True

    def _dispatch_outbound(self, item: dict) -> None:
        with self._lock:
            worker = next(
                (w for w in self._workers.values()
                 if w.inbox and w.inbox["id"] == item["inbox_id"]),
                None,
            )
        if worker is None or worker.state != ONLINE:
            # Worker not ready (still connecting, backoff, or removed).
            # Drop from inflight so the next long-poll retries instead of
            # waiting out the TTL.
            with self._inflight_lock:
                self._inflight.pop(item["id"], None)
            return
        try:
            worker.send_outbound(item)
            self._log("outbound", "ok",
                      f"sent {item['msg_type']} → {item['platform_conversation_id']}"
                      f" (id={item['id']})")
        except adapters.PermanentError as exc:
            self._log("outbound", "warn",
                      f"permanent failure · id={item['id']}: {exc}")
        except adapters.Unauthorized:
            self._log("outbound", "warn",
                      f"channel credential 失效 · id={item['id']}")
        except adapters.TransientError as exc:
            self._log("outbound", "warn",
                      f"transient · id={item['id']}: {exc}")
            # Drop from inflight so the next long-poll can retry.
            with self._inflight_lock:
                self._inflight.pop(item["id"], None)
        except Exception as exc:
            self._log("outbound", "err",
                      f"dispatch failed · id={item['id']}: {exc}")

    # ---- heartbeat actor ---------------------------------------------

    def _heartbeat_loop(self) -> None:
        self._beat()
        while not self._sleep(HEARTBEAT_S):
            self._beat()

    def _beat(self) -> None:
        try:
            self._studio.heartbeat()
        except HttpUnauthorized:
            self._log("heart", "err", "401 · Studio session 失效")
            self._auth_error("Studio session 失效，请重新登录")
        except Exception as exc:
            self._log("heart", "warn", f"heartbeat failed: {exc}")
