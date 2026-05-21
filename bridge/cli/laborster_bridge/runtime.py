"""BridgeRuntime — loop owner for one logged-in account.

Loops (one thread each unless noted):
  producer × N   per-inbox: list_conversations + fetch_new per DM conv,
                 ingested atomically with cursor advance.
  consumer  1s   unsent -> Studio /incoming   (only for active/takeover peers)
  heartbeat 15s  drop inboxes Studio no longer serves
  announce  60s  report DM peer directory (from list_conversations)
  active    10s  refresh takeover peer set
  outbound  LP   long-poll Studio queue -> adapter.send -> ack
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Callable

from . import adapters
from .events import Events
from .http import Unauthorized as HttpUnauthorized
from .store import LocalStore
from .studio_client import StudioClient

HEARTBEAT_S = 15
ANNOUNCE_S = 60
ACTIVE_PEERS_S = 10
CONSUMER_S = 1
CONSUMER_BATCH = 50
OUTBOUND_TIMEOUT_S = 30
PRODUCER_INTERVAL_S = 2


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
        # inbox_id -> {adapter, inbox, conv_map (peer_id→conv_id),
        #              peer_names (conv_id→(peer_id, display)), conv_count}
        self._adapters: dict[str, dict] = {}
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
        """Sleep, returning True if stop was requested."""
        return self._stop.wait(timeout=secs)

    # --- bootstrap ---
    def _bootstrap(self) -> None:
        self._last_error = None
        self._push_state("connecting")
        self._log("core", "info", f"starting · channels={len(self._channels)}")

        # Build adapters from credentials; resolve self_id (one HTTP each).
        logged_in: list[tuple[adapters.Adapter, str, str]] = []  # (adapter, platform, self_id)
        errors: list[str] = []
        for ch in self._channels:
            platform = ch.get("platform")
            try:
                factory = adapters.get(platform)
            except KeyError as exc:
                m = f"{platform}: {exc}"
                errors.append(m)
                self._log("adapter", "err", f"unknown platform · {m}")
                continue
            try:
                adapter = factory.build(ch["credential"])
                self_id = adapter.platform_self_id   # may raise
            except adapters.Unauthorized:
                m = f"{platform}: credential 失效，请重新 /channel add"
                errors.append(m)
                self._log("adapter", "err", f"channel auth failed · {m}")
                continue
            except adapters.TransientError as exc:
                m = f"{platform}: {exc}"
                errors.append(m)
                self._log("adapter", "warn", f"channel transient · {m}")
                continue
            except Exception as exc:
                m = f"{platform}: {exc}"
                errors.append(m)
                self._log("adapter", "err", f"channel build failed · {m}")
                continue
            self._log("adapter", "ok", f"{platform} self_id ok · {self_id}")
            logged_in.append((adapter, platform, self_id))

        if not logged_in:
            self._last_error = "无法连接任何 channel: " + " / ".join(errors)
            self._log("core", "err", "no channels logged in — stopping")
            self._push_state("offline")
            return

        try:
            r = self._studio.register_inboxes(
                [(platform, sid) for _, platform, sid in logged_in]
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

        inboxes = r["inboxes"]
        self._outbound_cursor = r["cursor"]
        self._log(
            "studio",
            "ok",
            f"inboxes registered · {len(inboxes)} inbox · cursor={r['cursor']}",
        )
        for adapter, platform, self_id in logged_in:
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
                continue
            entry = {
                "adapter": adapter,
                "inbox": inbox,
                "conv_map": {},      # peer_platform_id -> conversation_id
                "peer_names": {},    # conversation_id -> (peer_id, display)
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
        self._spawn(self._announce, "announce")
        self._spawn(self._loop_active_peers, "active-peers")
        self._spawn(self._outbound, "outbound")

    # --- producer (bounded fetch_new per conversation) ---

    def _producer(self, inbox_id: str) -> None:
        while not self._stop.is_set():
            try:
                self._poll_inbox(inbox_id)
            except adapters.Unauthorized:
                self._log(
                    "producer",
                    "err",
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
                    "producer",
                    "err",
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

        conv_map: dict[str, str] = {}
        peer_names: dict[str, tuple[str, str]] = {}
        for c in convs:
            if c.kind == "dm" and c.peers:
                peer = c.peers[0]
                conv_map[peer["platform_id"]] = c.id
                peer_names[c.id] = (peer["platform_id"], peer["display_name"])
        with self._lock:
            entry["conv_map"] = conv_map
            entry["peer_names"] = peer_names
            entry["conv_count"] = len(convs)

        for c in convs:
            if self._stop.is_set():
                return
            if c.kind != "dm" or not c.peers:
                continue
            peer = c.peers[0]
            since = self._store.get_cursor(inbox_id, c.id)
            events = adapter.fetch_new(c.id, since)
            if not events:
                continue
            new_cursor = events[-1].cursor
            event_dicts = [
                {
                    "sender_id": e.sender_id,
                    "sent_at": e.sent_at,
                    "msg_type": e.msg_type,
                    "content": e.content,
                }
                for e in events
            ]
            self._store.ingest(
                inbox_id,
                c.id,
                peer["platform_id"],
                peer["display_name"],
                event_dicts,
                new_cursor,
            )

    # --- consumer (unchanged shape; pushes unsent to Studio) ---

    def _consumer(self) -> None:
        while not self._sleep(CONSUMER_S):
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
                            "platform_msg_id": None,
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

    # --- heartbeat ---

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
            for inbox_id, _entry in removed:
                self._log("heart", "warn", f"inbox {inbox_id} removed by Studio")
            self._push_state("online")
        except HttpUnauthorized:
            self._log("heart", "err", "401 · session revoked")
            self._last_error = "Studio session 失效，请重新登录"
            self._auth_error()
            self._push_state("error401")
            self.stop()
        except Exception as exc:
            self._log("heart", "warn", f"heartbeat failed: {exc}")

    # --- announce ---

    def _announce(self) -> None:
        while True:
            with self._lock:
                items = list(self._adapters.items())
            for inbox_id, entry in items:
                try:
                    convs = entry["adapter"].list_conversations()
                    peers = [
                        {
                            "peer_platform_id": c.peers[0]["platform_id"],
                            "display_name": c.peers[0]["display_name"],
                        }
                        for c in convs
                        if c.kind == "dm" and c.peers
                    ]
                    self._studio.announce_peers(inbox_id, peers)
                except adapters.Unauthorized:
                    self._log(
                        "announce",
                        "warn",
                        f"inbox={inbox_id}: channel credential 失效，跳过 announce",
                    )
                except Exception as exc:
                    self._log("announce", "warn", f"inbox={inbox_id}: {exc}")
            if self._sleep(ANNOUNCE_S):
                return

    # --- active peers ---

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

    # --- outbound ---

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
            self._studio.ack_outbound(item["id"], "failed", "inbox not found")
            return
        adapter = entry["adapter"]
        conv_id = entry.get("conv_map", {}).get(item["peer_platform_id"])
        if conv_id is None:
            # Cache miss — refresh directory once.
            try:
                convs = adapter.list_conversations()
            except adapters.Unauthorized:
                self._studio.ack_outbound(
                    item["id"], "failed", "channel credential 失效"
                )
                return
            except Exception as exc:
                self._studio.ack_outbound(
                    item["id"], "failed", f"conv lookup failed: {exc}"
                )
                return
            conv_map = {
                c.peers[0]["platform_id"]: c.id
                for c in convs
                if c.kind == "dm" and c.peers
            }
            with self._lock:
                entry["conv_map"] = conv_map
            conv_id = conv_map.get(item["peer_platform_id"])
        if conv_id is None:
            self._studio.ack_outbound(item["id"], "failed", "conversation not found")
            return

        payload = adapters.OutboundPayload(
            msg_type=item["msg_type"], content=item["content"]
        )
        try:
            adapter.send(conv_id, payload)
            self._studio.ack_outbound(item["id"], "sent", "")
            self._log(
                "outbound",
                "ok",
                f"sent {payload.msg_type} to {item['peer_platform_id']}",
            )
        except adapters.PermanentError as exc:
            self._log("outbound", "warn", f"permanent failure: {exc}")
            self._studio.ack_outbound(item["id"], "failed", str(exc))
        except adapters.Unauthorized:
            self._studio.ack_outbound(
                item["id"], "failed", "channel credential 失效"
            )
        except Exception as exc:
            self._log("outbound", "err", f"dispatch failed: {exc}")
            self._studio.ack_outbound(item["id"], "failed", str(exc))
