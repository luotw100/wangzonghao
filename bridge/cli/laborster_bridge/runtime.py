"""BridgeRuntime — port of runtime.ts using threads instead of async.

Loops (one thread each unless noted):
  producer × N   per-inbox scan -> dedup store
  consumer  1s   unsent -> Studio /incoming   (only for active/takeover peers)
  heartbeat 15s  drop inboxes Studio no longer serves
  announce  60s  report peer directory
  active    10s  refresh takeover peer set
  outbound  LP   long-poll Studio queue -> chat send -> ack
"""

from __future__ import annotations

import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import adapters
from .events import Events
from .http import Unauthorized
from .store import LocalStore
from .studio_client import StudioClient

HEARTBEAT_S = 15
ANNOUNCE_S = 60
ACTIVE_PEERS_S = 10
CONSUMER_S = 1
CONSUMER_BATCH = 50
OUTBOUND_TIMEOUT_S = 30


class BridgeRuntime:
    def __init__(
        self,
        studio: StudioClient,
        channels: list[dict],
        store: LocalStore,
        events: Events,
        base_info: Callable[[], dict],
        on_auth_error: Callable[[], None],
    ) -> None:
        self._studio = studio
        self._channels = channels
        self._store = store
        self._events = events
        self._base_info = base_info
        self._on_auth_error = on_auth_error

        self._lock = threading.Lock()  # guards _adapters
        self._adapters: dict[str, dict] = {}  # inbox_id -> {adapter, inbox, cursors, label}
        self._active_peers: set[str] = set()
        self._outbound_cursor = 0
        self._last_error: str | None = None
        self._stop = threading.Event()
        self._threads: list[threading.Thread] = []

    # --- lifecycle ---
    def start(self) -> None:
        t = threading.Thread(target=self._bootstrap, name="bootstrap", daemon=True)
        t.start()
        self._threads.append(t)

    def _auth_error(self) -> None:
        # A runtime that has been stopped (e.g. superseded by _ensure)
        # must not run its 401 handler — it could clear a token a newer
        # runtime / fresh /login already replaced.
        if self._stop.is_set():
            return
        self._on_auth_error()

    def stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        with self._lock:
            adapters = list(self._adapters.values())
        for e in adapters:
            e["adapter"].stop()
        for t in self._threads:
            if t is not threading.current_thread():
                t.join(timeout=2)
        with self._lock:
            self._adapters.clear()
        self._push_state("idle")
        self._store.close()
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
                "handle": e["label"],
                "platform_self_id": e["adapter"].platform_self_id,
                "online": True,
                "peers_count": len(e["cursors"]),
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
        """Sleep, returning True if stop was requested."""
        return self._stop.wait(timeout=secs)

    # --- bootstrap ---
    def _bootstrap(self) -> None:
        self._last_error = None
        self._push_state("connecting")
        self._log("core", "info", f"starting · channels={len(self._channels)}")

        logged_in = []
        errors = []
        for ch in self._channels:
            label = ch["username"]
            platform = ch["platform"]
            token = ch["token"]
            try:
                factory = adapters.get(platform)
            except KeyError as exc:
                m = f"{label}: {exc}"
                self._log("adapter", "err", f"unknown platform · {m}")
                errors.append(m)
                continue
            adapter = factory.build(token, label)
            try:
                self_id = adapter.resolve_self()
                self._log("adapter", "ok", f"{platform} token ok · {label}")
                logged_in.append((adapter, self_id, label, platform))
            except Unauthorized:
                m = f"{label}: {platform} token 失效"
                self._log("adapter", "err", f"{platform} auth failed · {m}")
                errors.append(m)
            except Exception as exc:
                m = f"{label}: {exc}"
                self._log("adapter", "err", f"{platform} resolve failed · {m}")
                errors.append(m)

        if not logged_in:
            self._last_error = "无法连接聊天平台: " + " / ".join(errors)
            self._log("core", "err", "no channels logged in — stopping")
            self._push_state("offline")
            return

        try:
            r = self._studio.register_inboxes(
                [(platform, sid) for _, sid, _, platform in logged_in]
            )
        except Unauthorized:
            self._last_error = "Studio session 失效，请重新登录"
            self._auth_error()
            self._push_state("error401")
            return
        except Exception as exc:
            self._last_error = f"Studio 注册 channel 失败: {exc}"
            self._log("studio", "err", f"register inboxes failed: {exc}")
            self._push_state("offline")
            return

        inboxes = r["inboxes"]
        self._outbound_cursor = r["cursor"]
        self._log(
            "studio",
            "ok",
            f"inboxes registered · {len(inboxes)} inbox · cursor={r['cursor']}",
        )
        if r["no_persona"]:
            self._log("studio", "warn", "Studio 账号还没有 Persona，自动回复不会触发")

        for adapter, self_id, label, platform in logged_in:
            inbox = next(
                (
                    ib for ib in inboxes
                    if ib["platform"] == platform and ib["platform_self_id"] == self_id
                ),
                None,
            )
            if not inbox:
                self._log("adapter", "warn", f"no inbox for {label}")
                continue
            entry = {
                "adapter": adapter,
                "inbox": inbox,
                "cursors": self._store.get_cursors(inbox["id"]),
                "label": label,
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
        self._spawn(self._announce, "announce")
        self._spawn(self._loop_active_peers, "active-peers")
        self._spawn(self._outbound, "outbound")

    # --- loops ---
    def _producer(self, inbox_id: str) -> None:
        # Supervised: if scan() raises, restart it (same cursors) unless the
        # daemon is stopping or Studio has dropped this inbox (heartbeat
        # removes it from _adapters, which ends the loop).
        while not self._stop.is_set():
            with self._lock:
                entry = self._adapters.get(inbox_id)
            if entry is None:
                return
            try:
                self._run_producer(inbox_id, entry)
            except Exception as exc:
                if self._stop.is_set():
                    return
                self._log("producer", "err", f"inbox={inbox_id}: {exc} — restart in 3s")
                if self._sleep(3):
                    return

    def _run_producer(self, inbox_id: str, entry: dict) -> None:
        for msg in entry["adapter"].scan(entry["cursors"]):
            if self._stop.is_set():
                break
            lh = LocalStore.local_hash(
                inbox_id,
                msg["peer_id"],
                msg["sender_id"],
                msg["sent_at"],
                msg["msg_type"],
                msg["content"],
            )
            self._store.insert_message(
                {
                    "inbox_id": inbox_id,
                    "peer_id": msg["peer_id"],
                    "peer_display_name": msg["peer_display_name"],
                    "platform_msg_id": msg["platform_msg_id"],
                    "sender_id": msg["sender_id"],
                    "sent_at": msg["sent_at"],
                    "msg_type": msg["msg_type"],
                    "content": msg["content"],
                    "mime_type": None,
                    "local_hash": lh,
                }
            )

    def _consumer(self) -> None:
        while not self._sleep(CONSUMER_S):
            # The takeover set is the only gate (empty => forward nothing).
            rows = self._store.get_unsent(CONSUMER_BATCH, self._active_peers)
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
                            "peer_id": r.peer_id,
                            "peer_display_name": r.peer_display_name,
                            "platform_msg_id": r.platform_msg_id,
                            "sender_id": r.sender_id,
                            "msg_type": r.msg_type,
                            "content": r.content,
                            "sent_at": r.sent_at,
                        }
                        for r in batch
                    ]
                )
                self._store.mark_sent([r.id for r in batch])
            except Unauthorized:
                return  # heartbeat handles 401
            except Exception as exc:
                self._log("consumer", "warn", f"push failed: {exc}")

    def _heartbeat(self) -> None:
        self._beat()
        while not self._sleep(HEARTBEAT_S):
            self._beat()

    def _beat(self) -> None:
        try:
            res = self._studio.heartbeat()
            active_ids = {i["id"] for i in res["inboxes"]}
            with self._lock:
                removed = [
                    (i, self._adapters.pop(i))
                    for i in list(self._adapters)
                    if i not in active_ids
                ]
            for inbox_id, entry in removed:
                self._log("heart", "warn", f"inbox {inbox_id} removed by Studio")
                entry["adapter"].stop()
            self._push_state("online")
        except Unauthorized:
            self._log("heart", "err", "401 · session revoked")
            self._last_error = "Studio session 失效，请重新登录"
            self._auth_error()
            self._push_state("error401")
            self.stop()
        except Exception as exc:
            self._log("heart", "warn", f"heartbeat failed: {exc}")

    def _announce(self) -> None:
        while True:
            with self._lock:
                items = list(self._adapters.items())
            for inbox_id, entry in items:
                try:
                    peers = entry["adapter"].list_peers()
                    self._studio.announce_peers(inbox_id, peers)
                except Exception as exc:
                    self._log("announce", "warn", f"inbox={inbox_id}: {exc}")
            if self._sleep(ANNOUNCE_S):
                return

    def _loop_active_peers(self) -> None:
        while True:
            try:
                peers = self._studio.get_active_peers()
                self._active_peers = {
                    f"{p['inbox_id']}|{p['peer_platform_id']}" for p in peers
                }
            except Exception as exc:
                self._log("active", "warn", f"active-peers refresh failed: {exc}")
            if self._sleep(ACTIVE_PEERS_S):
                return

    def _outbound(self) -> None:
        while not self._stop.is_set():
            try:
                items = self._studio.get_outbound(
                    self._outbound_cursor, OUTBOUND_TIMEOUT_S
                )
                for item in items:
                    if self._stop.is_set():
                        break
                    self._outbound_cursor = max(self._outbound_cursor, item["id"])
                    self._dispatch_outbound(item)
            except Unauthorized:
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
            self._studio.ack_outbound(item["id"], "failed", "inbox not found")
            return
        try:
            if item["msg_type"] == "text":
                pid = entry["adapter"].send(item["peer_platform_id"], item["content"])
                self._studio.ack_outbound(item["id"], "sent", pid)
                self._log("outbound", "ok", f"sent text to {item['peer_platform_id']}")
            else:
                self._log(
                    "outbound", "warn", "media outbound not supported for chat adapter"
                )
                self._studio.ack_outbound(item["id"], "failed", "media not supported")
        except Exception as exc:
            self._log("outbound", "err", f"dispatch failed: {exc}")
            self._studio.ack_outbound(item["id"], "failed", str(exc))
