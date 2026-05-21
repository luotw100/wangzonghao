"""SQLite local store: incoming dedup queue + per-conversation cursors.

Single connection guarded by a lock (WAL mode) to serialize writes from
the daemon's worker threads.

Two tables:

* ``local_messages`` — Bridge's inbox-side staging queue. Rows are
  inserted on ``ingest`` (incoming from adapter), drained on
  ``mark_sent`` (after a successful push to Studio). Dedup is by
  ``(inbox_id, local_hash)``.
* ``conv_cursors`` — per ``(inbox_id, conversation_id)`` opaque cursor
  string; the resume point the adapter handed us with the last ingested
  event. Updated atomically with the message insert.
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
  conversation_id   TEXT NOT NULL,
  peer_id           TEXT NOT NULL,
  peer_display_name TEXT NOT NULL,
  sender_id         TEXT NOT NULL,
  sent_at           TEXT NOT NULL,
  msg_type          TEXT NOT NULL,
  content           TEXT NOT NULL,
  local_hash        TEXT NOT NULL,
  sent              INTEGER NOT NULL DEFAULT 0,
  UNIQUE(inbox_id, local_hash)
);
CREATE INDEX IF NOT EXISTS idx_unsent ON local_messages(sent, id);
CREATE INDEX IF NOT EXISTS idx_conv ON local_messages(inbox_id, conversation_id, id);

CREATE TABLE IF NOT EXISTS conv_cursors (
  inbox_id        TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  cursor          TEXT,
  updated_at      TEXT,
  PRIMARY KEY (inbox_id, conversation_id)
);
"""


@dataclass
class LocalMessage:
    id: int
    inbox_id: str
    conversation_id: str
    peer_id: str
    peer_display_name: str
    sender_id: str
    sent_at: str
    msg_type: str
    content: str
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
        conversation_id: str,
        sender_id: str,
        sent_at: str,
        msg_type: str,
        content: str,
    ) -> str:
        joined = "\x00".join(
            [inbox_id, conversation_id, sender_id, sent_at, msg_type, content]
        )
        return hashlib.sha256(joined.encode("utf-8")).hexdigest()

    # ---- cursors ----------------------------------------------------

    def get_cursor(self, inbox_id: str, conversation_id: str) -> str | None:
        with self._lock:
            if self._closed:
                return None
            row = self._db.execute(
                "SELECT cursor FROM conv_cursors "
                "WHERE inbox_id = ? AND conversation_id = ?",
                (inbox_id, conversation_id),
            ).fetchone()
        return row["cursor"] if row else None

    # ---- ingest -----------------------------------------------------

    def ingest(
        self,
        inbox_id: str,
        conversation_id: str,
        peer_id: str,
        peer_display_name: str,
        events: list[dict],
        new_cursor: str | None,
    ) -> int:
        """Atomically insert events and advance the conversation cursor.

        Returns the number of newly-inserted rows. Dups (same
        local_hash) are silently skipped.
        """
        if not events and new_cursor is None:
            return 0
        inserted = 0
        with self._lock:
            if self._closed:
                return 0
            try:
                self._db.execute("BEGIN IMMEDIATE")
                for e in events:
                    lh = self.local_hash(
                        inbox_id,
                        conversation_id,
                        e["sender_id"],
                        e["sent_at"],
                        e["msg_type"],
                        e["content"],
                    )
                    cur = self._db.execute(
                        """INSERT OR IGNORE INTO local_messages
                           (inbox_id, conversation_id, peer_id, peer_display_name,
                            sender_id, sent_at, msg_type, content, local_hash)
                           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                        (
                            inbox_id,
                            conversation_id,
                            peer_id,
                            peer_display_name,
                            e["sender_id"],
                            e["sent_at"],
                            e["msg_type"],
                            e["content"],
                            lh,
                        ),
                    )
                    if cur.rowcount > 0:
                        inserted += 1
                if new_cursor is not None:
                    self._db.execute(
                        """INSERT INTO conv_cursors
                             (inbox_id, conversation_id, cursor, updated_at)
                           VALUES (?, ?, ?, datetime('now'))
                           ON CONFLICT(inbox_id, conversation_id) DO UPDATE
                             SET cursor = excluded.cursor,
                                 updated_at = excluded.updated_at""",
                        (inbox_id, conversation_id, new_cursor),
                    )
                self._db.execute("COMMIT")
            except BaseException:
                self._db.execute("ROLLBACK")
                raise
        return inserted

    # ---- outbound staging ------------------------------------------

    def get_unsent(self, limit: int, active_peers: set[str]) -> list[LocalMessage]:
        """Unsent messages whose (inbox, peer) is in the takeover set.

        The takeover set is the *only* gate: an empty set means nothing is
        being taken over, so nothing is forwarded.
        """
        if not active_peers:
            return []
        with self._lock:
            if self._closed:
                return []
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

    def mark_sent(self, ids: list[int]) -> None:
        if not ids:
            return
        with self._lock:
            if self._closed:
                return
            self._db.executemany(
                "UPDATE local_messages SET sent = 1 WHERE id = ?",
                [(i,) for i in ids],
            )
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
