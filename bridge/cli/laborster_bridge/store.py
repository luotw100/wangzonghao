"""SQLite dedup store. 1:1 port of the former local-store.ts.

A single connection guarded by a lock (WAL mode) — the TS side used a
synchronous single-instance better-sqlite3; this preserves that
semantics across the daemon's worker threads.
"""

from __future__ import annotations

import hashlib
import sqlite3
import threading
from dataclasses import dataclass

_SCHEMA = """
CREATE TABLE IF NOT EXISTS local_messages (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  inbox_id          TEXT NOT NULL,
  peer_id           TEXT NOT NULL,
  peer_display_name TEXT NOT NULL,
  platform_msg_id   TEXT,
  sender_id         TEXT NOT NULL,
  sent_at           TEXT NOT NULL,
  msg_type          TEXT NOT NULL,
  content           TEXT NOT NULL,
  mime_type         TEXT,
  local_hash        TEXT NOT NULL,
  sent              INTEGER NOT NULL DEFAULT 0,
  UNIQUE(inbox_id, local_hash)
);
CREATE INDEX IF NOT EXISTS idx_unsent ON local_messages(sent, id);
CREATE INDEX IF NOT EXISTS idx_cursor ON local_messages(inbox_id, peer_id, id);
"""


@dataclass
class LocalMessage:
    id: int
    inbox_id: str
    peer_id: str
    peer_display_name: str
    platform_msg_id: str | None
    sender_id: str
    sent_at: str
    msg_type: str
    content: str
    mime_type: str | None
    local_hash: str
    sent: int


class LocalStore:
    def __init__(self, db_path: str) -> None:
        self._lock = threading.Lock()
        self._closed = False
        self._db = sqlite3.connect(db_path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(_SCHEMA)
        self._db.commit()

    @staticmethod
    def local_hash(
        inbox_id: str,
        peer_id: str,
        sender_id: str,
        sent_at: str,
        msg_type: str,
        content: str,
    ) -> str:
        joined = "\x00".join([inbox_id, peer_id, sender_id, sent_at, msg_type, content])
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    def get_cursors(self, inbox_id: str) -> dict[str, str | None]:
        with self._lock:
            if self._closed:
                return {}
            rows = self._db.execute(
                """SELECT peer_id, MAX(platform_msg_id) AS last_id
                   FROM local_messages
                   WHERE inbox_id = ? AND platform_msg_id IS NOT NULL
                   GROUP BY peer_id""",
                (inbox_id,),
            ).fetchall()
        return {r["peer_id"]: r["last_id"] for r in rows}

    def insert_message(self, m: dict) -> bool:
        with self._lock:
            if self._closed:
                return False
            cur = self._db.execute(
                """INSERT OR IGNORE INTO local_messages
                   (inbox_id, peer_id, peer_display_name, platform_msg_id, sender_id,
                    sent_at, msg_type, content, mime_type, local_hash)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    m["inbox_id"],
                    m["peer_id"],
                    m["peer_display_name"],
                    m["platform_msg_id"],
                    m["sender_id"],
                    m["sent_at"],
                    m["msg_type"],
                    m["content"],
                    m["mime_type"],
                    m["local_hash"],
                ),
            )
            self._db.commit()
            return cur.rowcount > 0

    def get_unsent(self, limit: int, active_peers: set[str] | None) -> list[LocalMessage]:
        if active_peers is not None and len(active_peers) == 0:
            return []
        with self._lock:
            if self._closed:
                return []
            if active_peers is None:
                rows = self._db.execute(
                    "SELECT * FROM local_messages WHERE sent = 0 ORDER BY id LIMIT ?",
                    (limit,),
                ).fetchall()
            else:
                keys = list(active_peers)
                placeholders = ",".join("(?,?)" for _ in keys)
                params: list = []
                for k in keys:
                    inbox_id, _, peer_id = k.partition("|")
                    params += [inbox_id, peer_id]
                params.append(limit)
                rows = self._db.execute(
                    f"""SELECT * FROM local_messages
                        WHERE sent = 0 AND (inbox_id, peer_id) IN ({placeholders})
                        ORDER BY id LIMIT ?""",
                    params,
                ).fetchall()
        return [LocalMessage(**dict(r)) for r in rows]

    def mark_sent(self, row_id: int) -> None:
        with self._lock:
            if self._closed:
                return
            self._db.execute("UPDATE local_messages SET sent = 1 WHERE id = ?", (row_id,))
            self._db.commit()

    def count_unsent(self) -> int:
        with self._lock:
            if self._closed:
                return 0
            return self._db.execute(
                "SELECT COUNT(*) AS n FROM local_messages WHERE sent = 0"
            ).fetchone()["n"]

    def count_recent_incoming(self, since_iso: str) -> int:
        with self._lock:
            if self._closed:
                return 0
            return self._db.execute(
                "SELECT COUNT(*) AS n FROM local_messages WHERE sent_at >= ? AND sent = 1",
                (since_iso,),
            ).fetchone()["n"]

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            self._db.close()
