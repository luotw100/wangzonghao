"""Single SQLite per account — the only on-disk state.

One file per Studio account, at ``<state_root>/<account_id>/state.db``.

Design rule: bridge is a message relay. Studio is the source of truth for
everything except (a) the credentials we need to talk to platforms and
(b) the bookkeeping we need to resume a relay across restarts. So this
file holds only four tables:

* ``kv``              — startup-essential values:
                          ``studio_token``      — Studio session token.
                          ``machine_id``        — Studio-issued, sent as
                                                  a header on every call.
                          ``last_active_at``    — UTC ISO; pure local
                                                  decision for "which
                                                  account to autostart".
                          ``display_name``      — RENDER CACHE ONLY. Re-
                                                  written from Studio's
                                                  handshake response so
                                                  the account picker can
                                                  show a name before the
                                                  daemon comes up. Never
                                                  read as truth.
* ``channels``        — one row per bound channel. The only durable
                        per-channel state is ``platform`` (which adapter)
                        and ``credential_json`` (the platform token).
                        Inbox id is Studio's — we re-fetch it on every
                        connect, never cache.
* ``local_messages``  — incoming dedup + relay queue (kept for the
                        ``(inbox_id, client_id)`` uniqueness, even after
                        upload).
* ``conv_cursors``    — per-conversation opaque resume cursor for the
                        adapter; orphans are kept so re-adding a channel
                        resumes where we left off.

If the on-disk schema doesn't match :data:`_SCHEMA_VERSION`, the db is
deleted and recreated. Migration is intentionally not implemented —
bridge state is recoverable (re-login Studio + re-add channel) and the
shape is still changing.

Opened with a POSIX ``flock`` (LOCK_EX|LOCK_NB) so two bridge processes
can't share an account. Read-only metadata queries used to enumerate
accounts at startup bypass the lock — SQLite WAL allows readers to
co-exist with the single writer.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

_SCHEMA_VERSION = 2

_SCHEMA = """
CREATE TABLE IF NOT EXISTS kv (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS channels (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  platform        TEXT    NOT NULL,
  credential_json TEXT    NOT NULL
);

CREATE TABLE IF NOT EXISTS local_messages (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  inbox_id          TEXT NOT NULL,
  conversation_id   TEXT NOT NULL,    -- adapter's platform_conversation_id
  client_id         TEXT NOT NULL,    -- adapter-decided stable id
  sender_id         TEXT,             -- NULL = self
  sent_at           TEXT NOT NULL,
  msg_type          TEXT NOT NULL,
  content           TEXT NOT NULL,
  sent              INTEGER NOT NULL DEFAULT 0,
  UNIQUE(inbox_id, client_id)
);
CREATE INDEX IF NOT EXISTS idx_unsent ON local_messages(sent, id);
CREATE INDEX IF NOT EXISTS idx_conv   ON local_messages(inbox_id, conversation_id, id);

CREATE TABLE IF NOT EXISTS conv_cursors (
  inbox_id        TEXT NOT NULL,
  conversation_id TEXT NOT NULL,
  cursor          TEXT,
  updated_at      TEXT,
  PRIMARY KEY (inbox_id, conversation_id)
);
"""


class StoreLockError(RuntimeError):
    """Another process already holds this account dir."""


@dataclass
class Channel:
    id: int
    platform: str
    credential: dict


@dataclass
class LocalMessage:
    id: int
    inbox_id: str
    conversation_id: str
    client_id: str
    sender_id: str | None
    sent_at: str
    msg_type: str
    content: str
    sent: int


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


class Store:
    def __init__(self, db_file: Path) -> None:
        self._path = Path(db_file)
        self._lock = threading.Lock()
        self._closed = False
        self._lock_fh = None

        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._acquire_flock()
        self._open_with_schema_check()
        try:
            os.chmod(self._path, 0o600)
        except OSError:
            pass
        self.kv_set("last_active_at", _now_iso())

    def _open_with_schema_check(self) -> None:
        """Open the db; nuke and recreate if schema version doesn't match.

        Cheaper than maintaining migrations while the shape still moves.
        Bridge state is recoverable — user re-logs Studio + re-adds channel.
        """
        if self._path.exists():
            try:
                probe = sqlite3.connect(str(self._path))
                probe.execute(
                    "CREATE TABLE IF NOT EXISTS meta(version INTEGER)"
                )
                row = probe.execute("SELECT version FROM meta LIMIT 1").fetchone()
                probe.close()
            except sqlite3.Error:
                row = None
            if not row or row[0] != _SCHEMA_VERSION:
                self._nuke()

        self._db = sqlite3.connect(str(self._path), check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.execute("PRAGMA journal_mode = WAL")
        self._db.executescript(_SCHEMA)
        self._db.execute("CREATE TABLE IF NOT EXISTS meta(version INTEGER)")
        self._db.execute("DELETE FROM meta")
        self._db.execute("INSERT INTO meta(version) VALUES (?)", (_SCHEMA_VERSION,))
        self._db.commit()

    def _nuke(self) -> None:
        for suffix in ("", "-wal", "-shm"):
            p = Path(str(self._path) + suffix)
            try:
                p.unlink()
            except FileNotFoundError:
                pass
            except OSError:
                pass

    def _acquire_flock(self) -> None:
        # Windows: skip — the GUI binary already enforces a singleton via
        # its own lock file. CLI on Windows is dev-only.
        if sys.platform == "win32":
            return
        import fcntl

        lock_path = self._path.with_name(self._path.name + ".lock")
        fh = open(lock_path, "a+")
        try:
            fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            fh.close()
            raise StoreLockError(
                f"另一个 bridge 进程正在使用 {self._path.parent}"
            ) from exc
        self._lock_fh = fh

    # ---- kv -----------------------------------------------------------

    def kv_get(self, key: str) -> str | None:
        with self._lock:
            if self._closed:
                return None
            row = self._db.execute(
                "SELECT value FROM kv WHERE key = ?", (key,)
            ).fetchone()
        return row["value"] if row else None

    def kv_set(self, key: str, value: str | None) -> None:
        with self._lock:
            if self._closed:
                return
            if value is None:
                self._db.execute("DELETE FROM kv WHERE key = ?", (key,))
            else:
                self._db.execute(
                    "INSERT INTO kv(key, value) VALUES(?, ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (key, value),
                )
            self._db.commit()

    # ---- channels -----------------------------------------------------

    def channels(self) -> list[Channel]:
        with self._lock:
            if self._closed:
                return []
            rows = self._db.execute(
                "SELECT id, platform, credential_json FROM channels ORDER BY id"
            ).fetchall()
        return [
            Channel(
                id=r["id"],
                platform=r["platform"],
                credential=json.loads(r["credential_json"]),
            )
            for r in rows
        ]

    def add_channel(self, platform: str, credential: dict) -> int:
        with self._lock:
            if self._closed:
                raise RuntimeError("store closed")
            cur = self._db.execute(
                "INSERT INTO channels(platform, credential_json) VALUES(?, ?)",
                (platform, json.dumps(credential, ensure_ascii=False)),
            )
            self._db.commit()
            return int(cur.lastrowid)

    def delete_channel(self, channel_id: int) -> bool:
        with self._lock:
            if self._closed:
                return False
            cur = self._db.execute(
                "DELETE FROM channels WHERE id = ?", (channel_id,)
            )
            self._db.commit()
        return cur.rowcount > 0

    def update_channel_credential(
        self, channel_id: int, credential: dict
    ) -> None:
        """Replace a channel's credential blob (e.g. after relogin)."""
        with self._lock:
            if self._closed:
                return
            self._db.execute(
                "UPDATE channels SET credential_json = ? WHERE id = ?",
                (json.dumps(credential, ensure_ascii=False), channel_id),
            )
            self._db.commit()

    # ---- ingest -------------------------------------------------------

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

    def ingest(
        self,
        inbox_id: str,
        conversation_id: str,
        events: list[dict],
        new_cursor: str | None,
    ) -> int:
        """Atomically insert events and advance the conversation cursor.

        Each event dict must contain: client_id (adapter-decided, str),
        sender_id (str|None where None=self), sent_at, msg_type, content.
        Dedup is by ``(inbox_id, client_id)`` via INSERT OR IGNORE — both
        local-side and wire-side use the same key.
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
                    cur = self._db.execute(
                        """INSERT OR IGNORE INTO local_messages
                           (inbox_id, conversation_id, client_id,
                            sender_id, sent_at, msg_type, content)
                           VALUES (?, ?, ?, ?, ?, ?, ?)""",
                        (
                            inbox_id,
                            conversation_id,
                            e["client_id"],
                            e["sender_id"],
                            e["sent_at"],
                            e["msg_type"],
                            e["content"],
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

    # ---- outbound staging --------------------------------------------

    def get_unsent(
        self, limit: int, active_takeovers: set[str]
    ) -> list[LocalMessage]:
        """Unsent messages whose ``(inbox_id, conversation_id)`` is in the
        takeover set. The takeover set is the only gate: an empty set
        means nothing is being forwarded.

        Keys are formatted ``"{inbox_id}|{conversation_id}"``.
        """
        if not active_takeovers:
            return []
        with self._lock:
            if self._closed:
                return []
            keys = list(active_takeovers)
            placeholders = ",".join("(?,?)" for _ in keys)
            params: list = []
            for k in keys:
                inbox_id, _, conv_id = k.partition("|")
                params += [inbox_id, conv_id]
            params.append(limit)
            rows = self._db.execute(
                f"""SELECT * FROM local_messages
                    WHERE sent = 0 AND (inbox_id, conversation_id) IN ({placeholders})
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
                "SELECT COUNT(*) AS n FROM local_messages "
                "WHERE sent_at >= ? AND sent = 1",
                (since_iso,),
            ).fetchone()["n"]

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
            try:
                self._db.execute(
                    "INSERT INTO kv(key, value) VALUES('last_active_at', ?) "
                    "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    (_now_iso(),),
                )
                self._db.commit()
            except sqlite3.Error:
                pass
            self._db.close()
        if self._lock_fh is not None:
            try:
                self._lock_fh.close()
            except OSError:
                pass
            self._lock_fh = None


# ---- account enumeration (no flock; uses SQLite read-only mode) -------

def read_account_meta(db_file: Path) -> dict:
    """Read kv + channel_count from an account db without taking flock.

    Returns ``{}`` for missing/corrupt files so the caller can skip them.
    Tolerates schema-version mismatch (returns what it can read) so the
    account picker still works before the db gets nuked-and-recreated on
    first open.
    """
    if not db_file.exists():
        return {}
    try:
        conn = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    except sqlite3.Error:
        return {}
    try:
        conn.row_factory = sqlite3.Row
        meta: dict = {}
        try:
            meta = {
                r["key"]: r["value"]
                for r in conn.execute("SELECT key, value FROM kv").fetchall()
            }
        except sqlite3.Error:
            pass
        try:
            meta["channel_count"] = conn.execute(
                "SELECT COUNT(*) AS n FROM channels"
            ).fetchone()["n"]
        except sqlite3.Error:
            meta["channel_count"] = 0
        meta["has_token"] = "studio_token" in meta
        return meta
    finally:
        conn.close()


def list_accounts(state_root: Path) -> list[dict]:
    """Enumerate ``<state_root>/<account_id>/state.db``, newest first."""
    out: list[dict] = []
    if not state_root.is_dir():
        return out
    for sub in state_root.iterdir():
        if not sub.is_dir():
            continue
        db = sub / "state.db"
        meta = read_account_meta(db)
        if not meta:
            continue
        out.append(
            {
                "account_id": sub.name,
                "display_name": meta.get("display_name"),
                "machine_id": meta.get("machine_id"),
                "last_active_at": meta.get("last_active_at"),
                "has_token": meta.get("has_token", False),
                "channel_count": meta.get("channel_count", 0),
            }
        )
    out.sort(key=lambda x: x["last_active_at"] or "", reverse=True)
    return out
