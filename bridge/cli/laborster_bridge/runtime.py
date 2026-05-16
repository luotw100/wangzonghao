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

from .chat_adapter import ChatAdapter
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

    def stop(self) -> None:
        if self._stop.is_set():
            return
        self._stop.set()
        for e in self._adapters.values():
            e["adapter"].stop()
        for t in self._threads:
            if t is not threading.current_thread():
                t.join(timeout=2)
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
        channels = [
            {
                "inbox_id": e["inbox"]["id"],
                "handle": e["label"],
                "platform_self_id": e["adapter"]._self_id,
                "online": True,
                "peers_count": len(e["cursors"]),
            }
            for e in self._adapters.values()
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
            adapter = ChatAdapter(ch["chat_token"], label)
            try:
                self_id = adapter.resolve_self()
                self._log("adapter", "ok", f"chat token ok · {label}")
                logged_in.append((adapter, self_id, label))
            except Unauthorized:
                m = f"{label}: chat token 失效"
                self._log("adapter", "err", f"chat auth failed · {m}")
                errors.append(m)
            except Exception as exc:
                m = f"{label}: {exc}"
                self._log("adapter", "err", f"chat resolve failed · {m}")
                errors.append(m)

        if not logged_in:
            self._last_error = "无法连接聊天平台: " + " / ".join(errors)
            self._log("core", "err", "no channels logged in — stopping")
            self._push_state("offline")
            return

        try:
            r = self._studio.register_inboxes(
                [("chat", sid) for _, sid, _ in logged_in]
            )
        except Unauthorized:
            self._last_error = "Studio session 失效，请重新登录"
            self._on_auth_error()
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

        for adapter, self_id, label in logged_in:
            inbox = next(
                (ib for ib in inboxes if ib["platform_self_id"] == self_id), None
            )
            if not inbox:
                self._log("adapter", "warn", f"no inbox for {label}")
                continue
            self._adapters[inbox["id"]] = {
                "adapter": adapter,
                "inbox": inbox,
                "cursors": self._store.get_cursors(inbox["id"]),
                "label": label,
            }

        self._push_state("online")

        for inbox_id in list(self._adapters):
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
        entry = self._adapters[inbox_id]
        try:
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
        except Exception as exc:
            if not self._stop.is_set():
                self._log("producer", "err", f"inbox={inbox_id}: {exc}")

    def _consumer(self) -> None:
        while not self._sleep(CONSUMER_S):
            ap = self._active_peers if self._active_peers else None
            rows = self._store.get_unsent(CONSUMER_BATCH, ap)
            for row in rows:
                if row.inbox_id not in self._adapters:
                    self._store.mark_sent(row.id)
                    continue
                try:
                    self._studio.push_incoming(
                        [
                            {
                                "inbox_id": row.inbox_id,
                                "peer_id": row.peer_id,
                                "peer_display_name": row.peer_display_name,
                                "platform_msg_id": row.platform_msg_id,
                                "sender_id": row.sender_id,
                                "msg_type": row.msg_type,
                                "content": row.content,
                                "sent_at": row.sent_at,
                            }
                        ]
                    )
                    self._store.mark_sent(row.id)
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
            for inbox_id in list(self._adapters):
                if inbox_id not in active_ids:
                    self._log("heart", "warn", f"inbox {inbox_id} removed by Studio")
                    self._adapters[inbox_id]["adapter"].stop()
                    del self._adapters[inbox_id]
            self._push_state("online")
        except Unauthorized:
            self._log("heart", "err", "401 · session revoked")
            self._last_error = "Studio session 失效，请重新登录"
            self._on_auth_error()
            self._push_state("error401")
            self.stop()
        except Exception as exc:
            self._log("heart", "warn", f"heartbeat failed: {exc}")

    def _announce(self) -> None:
        while True:
            for inbox_id, entry in list(self._adapters.items()):
                try:
                    peers = entry["adapter"].list_peers()
                    self._studio.announce_peers(inbox_id, peers)
                except Exception:
                    pass
            if self._sleep(ANNOUNCE_S):
                return

    def _loop_active_peers(self) -> None:
        while True:
            try:
                peers = self._studio.get_active_peers()
                self._active_peers = {
                    f"{p['inbox_id']}|{p['peer_platform_id']}" for p in peers
                }
            except Exception:
                pass
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
                self._on_auth_error()
                self._push_state("error401")
                self.stop()
                return
            except Exception as exc:
                self._log("outbound", "warn", f"poll error: {exc}")
                if self._sleep(2):
                    return

    def _dispatch_outbound(self, item: dict) -> None:
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
