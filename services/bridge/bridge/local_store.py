"""Bridge local message store.

Persists every platform message seen (historical or live) in a local SQLite
database so that the consumer can send unsent messages to Studio reliably
across restarts and without depending on platform_msg_id stability.

Two-layer dedup:
- Local:  UNIQUE(inbox_id, local_hash) prevents Bridge from re-processing
          the same platform message twice.
- Remote: Studio computes msg_hash and rejects already-known messages,
          giving cross-device / cross-Bridge-instance safety.
"""

from __future__ import annotations

import hashlib
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def canonical_sent_at(dt: datetime) -> str:
    """Normalize a datetime to a fixed UTC ISO8601 string used in all hashes.

    Always 6 decimal places for microseconds so the format is stable even
    when the platform gives second-precision timestamps.
    """
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f+00:00")


def compute_local_hash(
    inbox_id: str,
    peer_id: str,
    sender_id: str,
    sent_at_canonical: str,
    msg_type: str,
    content: str,
) -> str:
    """SHA256 of null-separated fields.

    content must already be the *stored* form:
    - text messages:  the plain text
    - media messages: "sha256:{hex}" (hash of the file bytes)
    """
    raw = "\x00".join([inbox_id, peer_id, sender_id, sent_at_canonical, msg_type, content])
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class LocalMessage:
    inbox_id:            str
    peer_id:             str
    peer_display_name:   str
    sender_id:           str
    sent_at:             str           # canonical UTC ISO8601
    msg_type:            str           # text | image | audio | video | file
    content:             str           # text: plain text; media: "sha256:{hex}"
    local_hash:          str
    id:                  Optional[int] = None  # None before INSERT
    platform_msg_id:     Optional[str] = None
    mime_type:           Optional[str] = None  # populated for media messages
    sent:                bool = False


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class LocalStore:
    """SQLite-backed persistent store for Bridge inbound messages."""

    def __init__(self, db_path: Path) -> None:
        self._path = str(db_path)
        self._conn: Optional[sqlite3.Connection] = None

    def _conn_(self) -> sqlite3.Connection:
        if self._conn is None:
            self._conn = sqlite3.connect(self._path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        return self._conn

    def migrate(self) -> None:
        """Create tables and indexes if they don't exist. Safe to call on every start."""
        conn = self._conn_()
        conn.execute("PRAGMA journal_mode=WAL")
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS local_messages (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                inbox_id            TEXT    NOT NULL,
                peer_id             TEXT    NOT NULL,
                peer_display_name   TEXT    NOT NULL DEFAULT '',
                platform_msg_id     TEXT,
                sender_id           TEXT    NOT NULL,
                sent_at             TEXT    NOT NULL,
                msg_type            TEXT    NOT NULL,
                content             TEXT    NOT NULL,
                mime_type           TEXT,
                local_hash          TEXT    NOT NULL,
                sent                INTEGER NOT NULL DEFAULT 0
            );

            CREATE UNIQUE INDEX IF NOT EXISTS idx_local_hash
                ON local_messages(inbox_id, local_hash);

            CREATE INDEX IF NOT EXISTS idx_unsent
                ON local_messages(sent, id);

            CREATE INDEX IF NOT EXISTS idx_cursor
                ON local_messages(inbox_id, peer_id, id);
        """)
        conn.commit()

    def get_cursors(self, inbox_id: str) -> dict[str, str | None]:
        """Return {peer_id: last_platform_msg_id} for all peers in inbox_id.

        Uses the platform_msg_id of the highest-id (last-inserted) row per
        peer so that scan() can resume from where it left off.
        Only peers with at least one non-null platform_msg_id are returned.
        """
        conn = self._conn_()
        rows = conn.execute("""
            SELECT peer_id, platform_msg_id
            FROM local_messages
            WHERE inbox_id = ? AND platform_msg_id IS NOT NULL
              AND id IN (
                  SELECT MAX(id)
                  FROM local_messages
                  WHERE inbox_id = ? AND platform_msg_id IS NOT NULL
                  GROUP BY peer_id
              )
        """, (inbox_id, inbox_id)).fetchall()
        return {r["peer_id"]: r["platform_msg_id"] for r in rows}

    def insert_message(self, msg: LocalMessage) -> bool:
        """Insert a message. Returns True if inserted, False if local_hash already existed."""
        conn = self._conn_()
        conn.execute("""
            INSERT OR IGNORE INTO local_messages
                (inbox_id, peer_id, peer_display_name, platform_msg_id, sender_id,
                 sent_at, msg_type, content, mime_type, local_hash, sent)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0)
        """, (
            msg.inbox_id, msg.peer_id, msg.peer_display_name, msg.platform_msg_id,
            msg.sender_id, msg.sent_at, msg.msg_type, msg.content, msg.mime_type,
            msg.local_hash,
        ))
        conn.commit()
        return conn.execute("SELECT changes()").fetchone()[0] > 0

    def get_unsent(self, limit: int = 50) -> list[LocalMessage]:
        """Return up to `limit` unsent messages ordered by insertion id."""
        conn = self._conn_()
        rows = conn.execute("""
            SELECT id, inbox_id, peer_id, peer_display_name, platform_msg_id, sender_id,
                   sent_at, msg_type, content, mime_type, local_hash, sent
            FROM local_messages
            WHERE sent = 0
            ORDER BY id
            LIMIT ?
        """, (limit,)).fetchall()
        return [_row_to_msg(r) for r in rows]

    def mark_sent(self, msg_id: int) -> None:
        conn = self._conn_()
        conn.execute("UPDATE local_messages SET sent = 1 WHERE id = ?", (msg_id,))
        conn.commit()

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


def _row_to_msg(r: sqlite3.Row) -> LocalMessage:
    return LocalMessage(
        id=r["id"],
        inbox_id=r["inbox_id"],
        peer_id=r["peer_id"],
        peer_display_name=r["peer_display_name"],
        platform_msg_id=r["platform_msg_id"],
        sender_id=r["sender_id"],
        sent_at=r["sent_at"],
        msg_type=r["msg_type"],
        content=r["content"],
        mime_type=r["mime_type"],
        local_hash=r["local_hash"],
        sent=bool(r["sent"]),
    )
