"""BridgeRuntime — loop owner for one logged-in account (protocol v2).

Loops (one thread each unless noted):
  producer × N   per-inbox: list_conversations + diff-push /conversations
                 + fetch_new per conversation, ingested atomically with
                 cursor advance.
  consumer  1s   unsent -> Studio /incoming   (only for takeover convs)
  heartbeat 15s  pure heartbeat; 401 -> auth_error
  takeovers 10s  refresh takeover (inbox_id, conv_id) set
  outbound  LP   long-poll Studio /outbound -> adapter.send. No ack:
                 success path closes via /incoming auto-DELIVERED;
                 PermanentError just drops the message (lease-less).
                 Per-process in-flight set prevents same-id redispatch.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import adapters
from .events import Events
from .http import Unauthorized as HttpUnauthorized
from .store import Store
from .studio_client import StudioClient

HEARTBEAT_S = 15
TAKEOVERS_S = 10
CONSUMER_S = 1
CONSUMER_BATCH = 50
OUTBOUND_TIMEOUT_S = 30
PRODUCER_INTERVAL_S = 2


def _conv_signature(convs: list[adapters.Conversation]) -> tuple:
    """Stable hashable summary used to detect "anything changed"."""
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
    out = []
    for c in convs:
        out.append(
            {
                "platform_conversation_id": c.id,
                "kind": c.kind,
                "display_name": c.display_name,
                "members": [
                    {
                        "peer_platform_id": p["platform_id"],
                        "display_name": p["display_name"],
                    }
                    for p in c.peers
                ],
            }
        )
    return out


class BridgeRuntime:
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

        self._lock = threading.Lock()
        # inbox_id -> {adapter, inbox, conv_signature, conv_count}
        self._adapters: dict[str, dict] = {}
        # set of "inbox_id|platform_conversation_id" pulled from /takeovers
        self._active_takeovers: set[str] = set()
        # outbound ids currently being dispatched (so we don't redispatch
        # within the same process between long-polls).
        self._inflight_outbound: set[int] = set()
        self._last_error: str | None = None
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    # --- lifecycle ---
    def start(self) -> None:
        t = threading.Thread(target=self._bootstrap, name="bootstrap", daemon=True)
        t.start()
        self._threads.append(t)

    def _auth_error(self) -> None:
        if self._stop.is_set():
            return
        self._on_auth_error()

    def stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        for t in self._threads:
            if t is not threading.current_thread():
                t.join(timeout=2)
        with self._lock:
            self._adapters.clear()
        self._push_state("idle")
        self._log("core", "info", "daemon stopped")

    def is_running(self) -> bool:
        return not self._stop.is_set()

    # --- helpers ---
    def _log(self, src: str, level: str, msg: str) -> None:
        self._events.log(src, level, msg)

    def _push_state(self, status: str) -> None:
        with self._lock:
            entries = list(self._adapters.values())
        channels = [
            {
                "inbox_id": e["inbox"]["id"],
                "platform": e["inbox"]["platform"],
                "platform_self_id": e["inbox"]["platform_self_id"],
                "online": True,
                "conv_count": e.get("conv_count", 0),
            }
            for e in entries
        ]
        since = (datetime.now(timezone.utc) - timedelta(minutes=5)).strftime(
            "%Y-%m-%dT%H:%M:%S.000Z"
        )
        self._events.set_state(
            {
                **self._base_info(),
                "status": status,
                "channels": channels,
                "in_count_5m": self._store.count_recent_incoming(since),
                "outbound_pending": self._store.count_unsent(),
                "last_error": self._last_error,
            }
        )

    def _spawn(self, target, name: str) -> None:
        t = threading.Thread(target=target, name=name, daemon=True)
        t.start()
        self._threads.append(t)

    def _sleep(self, secs: float) -> bool:
        return self._stop.wait(timeout=secs)

    # --- bootstrap ---
    def _bootstrap(self) -> None:
        self._last_error = None
        self._push_state("connecting")
        channels = self._store.channels()
        self._log("core", "info", f"starting · channels={len(channels)}")

        logged_in: list[tuple[int, adapters.Adapter, str, str, str]] = []
        # (channel_id, adapter, platform, self_id, self_display)
        errors: list[str] = []
        for ch in channels:
            try:
                factory = adapters.get(ch.platform)
            except KeyError as exc:
                m = f"{ch.platform}: {exc}"
                errors.append(m)
                self._log("adapter", "err", f"unknown platform · {m}")
                continue
            try:
                adapter = factory.build(ch.credential)
                self_id = adapter.platform_self_id
                self_display = adapter.platform_self_display_name
            except adapters.Unauthorized:
                m = f"{ch.platform}: credential 失效，请重新 /channel add"
                errors.append(m)
                self._log("adapter", "err", f"channel auth failed · {m}")
                continue
            except adapters.TransientError as exc:
                m = f"{ch.platform}: {exc}"
                errors.append(m)
                self._log("adapter", "warn", f"channel transient · {m}")
                continue
            except Exception as exc:
                m = f"{ch.platform}: {exc}"
                errors.append(m)
                self._log("adapter", "err", f"channel build failed · {m}")
                continue
            self._log("adapter", "ok", f"{ch.platform} self_id ok · {self_id}")
            logged_in.append((ch.id, adapter, ch.platform, self_id, self_display))

        if not logged_in:
            self._last_error = "无法连接任何 channel: " + " / ".join(errors)
            self._log("core", "err", "no channels logged in — stopping")
            self._push_state("offline")
            return

        try:
            inboxes = self._studio.register_inboxes(
                [
                    {
                        "platform": platform,
                        "platform_self_id": sid,
                        "display_name": display,
                    }
                    for _, _, platform, sid, display in logged_in
                ]
            )
        except HttpUnauthorized:
            self._last_error = "Studio session 失效，请重新登录"
            self._auth_error()
            self._push_state("error401")
            return
        except Exception as exc:
            self._last_error = f"Studio 注册 channel 失败: {exc}"
            self._log("studio", "err", f"register inboxes failed: {exc}")
            self._push_state("offline")
            return

        self._log("studio", "ok", f"inboxes registered · {len(inboxes)} inbox")
        for channel_id, adapter, platform, self_id, _display in logged_in:
            inbox = next(
                (
                    ib
                    for ib in inboxes
                    if ib["platform"] == platform
                    and ib["platform_self_id"] == self_id
                ),
                None,
            )
            if not inbox:
                self._log("adapter", "warn", f"no inbox for {platform}/{self_id}")
                self._store.set_channel_inbox(channel_id, None)
                continue
            self._store.set_channel_inbox(channel_id, inbox["id"])
            entry = {
                "adapter": adapter,
                "inbox": inbox,
                "conv_signature": None,
                "conv_count": 0,
            }
            with self._lock:
                self._adapters[inbox["id"]] = entry

        self._push_state("online")

        with self._lock:
            inbox_ids = list(self._adapters)
        for inbox_id in inbox_ids:
            self._spawn(
                lambda i=inbox_id: self._producer(i), f"producer-{inbox_id}"
            )
        self._spawn(self._consumer, "consumer")
        self._spawn(self._heartbeat, "heartbeat")
        self._spawn(self._loop_takeovers, "takeovers")
        self._spawn(self._outbound, "outbound")

    # --- producer (diff-aware /conversations push + fetch_new) ---

    def _producer(self, inbox_id: str) -> None:
        while not self._stop.is_set():
            try:
                self._poll_inbox(inbox_id)
            except adapters.Unauthorized:
                self._log(
                    "producer", "err",
                    f"inbox={inbox_id}: channel credential 失效，停止本 channel",
                )
                with self._lock:
                    self._adapters.pop(inbox_id, None)
                self._push_state("degraded")
                return
            except adapters.TransientError as exc:
                if self._stop.is_set():
                    return
                self._log("producer", "warn", f"inbox={inbox_id}: {exc} — retry 3s")
                if self._sleep(3):
                    return
                continue
            except Exception as exc:
                if self._stop.is_set():
                    return
                self._log(
                    "producer", "err",
                    f"inbox={inbox_id}: unexpected {type(exc).__name__}: {exc} — retry 5s",
                )
                if self._sleep(5):
                    return
                continue
            if self._sleep(PRODUCER_INTERVAL_S):
                return

    def _poll_inbox(self, inbox_id: str) -> None:
        with self._lock:
            entry = self._adapters.get(inbox_id)
        if entry is None:
            return
        adapter = entry["adapter"]

        convs = adapter.list_conversations()
        sig = _conv_signature(convs)
        prev_sig = entry.get("conv_signature")
        if sig != prev_sig:
            try:
                self._studio.push_conversations(
                    inbox_id, _to_push_conversations(convs)
                )
                entry["conv_signature"] = sig
                self._log(
                    "producer", "ok",
                    f"inbox={inbox_id}: pushed {len(convs)} conversations (diff)",
                )
            except HttpUnauthorized:
                self._auth_error()
                return
            except Exception as exc:
                self._log("producer", "warn", f"push conversations failed: {exc}")
                # Don't update signature — retry next loop.
        entry["conv_count"] = len(convs)

        for c in convs:
            if self._stop.is_set():
                return
            since = self._store.get_cursor(inbox_id, c.id)
            events = adapter.fetch_new(c.id, since)
            if not events:
                continue
            new_cursor = events[-1].cursor
            event_dicts = [
                {
                    "client_id": e.client_id,
                    "sender_id": e.sender_id,
                    "sent_at": e.sent_at,
                    "msg_type": e.msg_type,
                    "content": e.content,
                }
                for e in events
            ]
            self._store.ingest(inbox_id, c.id, event_dicts, new_cursor)

    # --- consumer ---

    def _consumer(self) -> None:
        while not self._sleep(CONSUMER_S):
            rows = self._store.get_unsent(CONSUMER_BATCH, self._active_takeovers)
            if not rows:
                continue
            with self._lock:
                known = set(self._adapters)
            stale = [r.id for r in rows if r.inbox_id not in known]
            if stale:
                self._store.mark_sent(stale)
            batch = [r for r in rows if r.inbox_id in known]
            if not batch:
                continue
            try:
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
            except HttpUnauthorized:
                return  # heartbeat handles 401
            except Exception as exc:
                self._log("consumer", "warn", f"push failed: {exc}")

    # --- heartbeat (pure) ---

    def _heartbeat(self) -> None:
        self._beat()
        while not self._sleep(HEARTBEAT_S):
            self._beat()

    def _beat(self) -> None:
        try:
            self._studio.heartbeat()
        except HttpUnauthorized:
            self._log("heart", "err", "401 · session revoked")
            self._last_error = "Studio session 失效，请重新登录"
            self._auth_error()
            self._push_state("error401")
            self.stop()
        except Exception as exc:
            self._log("heart", "warn", f"heartbeat failed: {exc}")

    # --- takeovers ---

    def _loop_takeovers(self) -> None:
        while True:
            try:
                takeovers = self._studio.get_takeovers()
                self._active_takeovers = {
                    f"{t['inbox_id']}|{t['platform_conversation_id']}"
                    for t in takeovers
                }
            except HttpUnauthorized:
                self._auth_error()
                return
            except Exception as exc:
                self._log("takeover", "warn", f"refresh failed: {exc}")
            if self._sleep(TAKEOVERS_S):
                return

    # --- outbound ---

    def _outbound(self) -> None:
        while not self._stop.is_set():
            try:
                items = self._studio.get_outbound(OUTBOUND_TIMEOUT_S)
                for item in items:
                    if self._stop.is_set():
                        break
                    if item["id"] in self._inflight_outbound:
                        continue
                    self._inflight_outbound.add(item["id"])
                    self._dispatch_outbound(item)
            except HttpUnauthorized:
                self._last_error = "Studio session 失效，请重新登录"
                self._auth_error()
                self._push_state("error401")
                self.stop()
                return
            except Exception as exc:
                self._log("outbound", "warn", f"poll error: {exc}")
                if self._sleep(2):
                    return

    def _dispatch_outbound(self, item: dict) -> None:
        with self._lock:
            entry = self._adapters.get(item["inbox_id"])
        if not entry:
            # We just don't dispatch — Studio will keep re-offering it
            # until either the inbox comes back or someone cleans up.
            self._log("outbound", "warn", f"inbox not served · id={item['id']}")
            return
        adapter = entry["adapter"]
        conv_id = item["platform_conversation_id"]
        payload = adapters.OutboundPayload(
            msg_type=item["msg_type"], content=item["content"]
        )
        try:
            adapter.send(conv_id, payload)
            self._log(
                "outbound", "ok",
                f"sent {payload.msg_type} -> {conv_id} (id={item['id']})",
            )
        except adapters.PermanentError as exc:
            self._log("outbound", "warn", f"permanent failure · id={item['id']}: {exc}")
        except adapters.Unauthorized:
            self._log("outbound", "warn", f"channel credential 失效 · id={item['id']}")
        except Exception as exc:
            self._log("outbound", "err", f"dispatch failed · id={item['id']}: {exc}")
