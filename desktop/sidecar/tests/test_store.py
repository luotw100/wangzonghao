"""Unit tests for the per-account SQLite store.

Real SQLite, no mocks. The store is the only on-disk state in the relay,
so its dedup / cursor / takeover-gating contracts are the bugs that would
silently drop or duplicate messages — that's what these lock down.
"""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest

from laborster_bridge.store import (
    Store,
    StoreLockError,
    list_accounts,
    read_account_meta,
)


def _event(client_id: str, *, sender_id: str | None = "u1", content: str = "hi") -> dict:
    """One ingest event. Keys match Store.ingest's expected shape."""
    return {
        "client_id": client_id,
        "sender_id": sender_id,
        "sent_at": "2026-05-29T00:00:00.000Z",
        "msg_type": "text",
        "content": content,
    }


# --------------------------------------------------------------------- kv

def test_kv_set_get_update_delete(store: Store) -> None:
    assert store.kv_get("missing") is None

    store.kv_set("studio_token", "tok-1")
    assert store.kv_get("studio_token") == "tok-1"

    store.kv_set("studio_token", "tok-2")  # ON CONFLICT update
    assert store.kv_get("studio_token") == "tok-2"

    store.kv_set("studio_token", None)  # None deletes
    assert store.kv_get("studio_token") is None


def test_init_writes_last_active_at(store: Store) -> None:
    # Constructor stamps last_active_at so the account picker can sort.
    assert store.kv_get("last_active_at") is not None


# --------------------------------------------------------------- channels

def test_channels_add_list_delete(store: Store) -> None:
    assert store.channels() == []

    cid = store.add_channel("chat", {"token": "abc"})
    assert isinstance(cid, int)

    chans = store.channels()
    assert len(chans) == 1
    assert chans[0].platform == "chat"
    assert chans[0].credential == {"token": "abc"}  # JSON round-trips

    assert store.delete_channel(cid) is True
    assert store.delete_channel(cid) is False  # already gone
    assert store.channels() == []


def test_channels_ordered_by_id(store: Store) -> None:
    a = store.add_channel("chat", {})
    b = store.add_channel("chat", {})
    assert [c.id for c in store.channels()] == [a, b]


def test_channel_credential_non_ascii_roundtrip(store: Store) -> None:
    # ensure_ascii=False — credentials may carry non-ASCII display data.
    cid = store.add_channel("chat", {"name": "晚枫"})
    assert store.channels()[0].credential == {"name": "晚枫"}

    store.update_channel_credential(cid, {"name": "新名字"})
    assert store.channels()[0].credential == {"name": "新名字"}


# ----------------------------------------------------------------- ingest

def test_ingest_inserts_and_counts(store: Store) -> None:
    n = store.ingest("inb1", "conv1", [_event("c1"), _event("c2")], "cursor-1")
    assert n == 2
    assert store.count_unsent() == 2


def test_ingest_dedups_on_inbox_client_id(store: Store) -> None:
    store.ingest("inb1", "conv1", [_event("c1")], None)
    # Same (inbox_id, client_id) → INSERT OR IGNORE, not re-inserted.
    again = store.ingest("inb1", "conv1", [_event("c1")], None)
    assert again == 0
    assert store.count_unsent() == 1


def test_ingest_dedup_key_excludes_conversation(store: Store) -> None:
    """Dedup is (inbox_id, client_id) — conversation_id is NOT part of it.

    Same client_id under a different conversation in the same inbox is still
    treated as a duplicate. Locks down the current UNIQUE constraint.
    """
    store.ingest("inb1", "convA", [_event("dup")], None)
    n = store.ingest("inb1", "convB", [_event("dup")], None)
    assert n == 0


def test_ingest_advances_cursor(store: Store) -> None:
    assert store.get_cursor("inb1", "conv1") is None
    store.ingest("inb1", "conv1", [_event("c1")], "cur-1")
    assert store.get_cursor("inb1", "conv1") == "cur-1"
    # None cursor leaves the existing one untouched.
    store.ingest("inb1", "conv1", [_event("c2")], None)
    assert store.get_cursor("inb1", "conv1") == "cur-1"
    # A new cursor overwrites.
    store.ingest("inb1", "conv1", [_event("c3")], "cur-2")
    assert store.get_cursor("inb1", "conv1") == "cur-2"


def test_ingest_empty_noop(store: Store) -> None:
    # No events and no cursor → short-circuits to 0, writes nothing.
    assert store.ingest("inb1", "conv1", [], None) == 0
    assert store.count_unsent() == 0


# ------------------------------------------------- outbound / takeover gate

def test_get_unsent_gated_by_takeover_set(store: Store) -> None:
    store.ingest("inb1", "conv1", [_event("c1")], None)
    store.ingest("inb1", "conv2", [_event("c2")], None)

    # Empty takeover set forwards nothing.
    assert store.get_unsent(10, set()) == []

    # Only the conversation in the takeover set is returned.
    got = store.get_unsent(10, {"inb1|conv1"})
    assert [m.client_id for m in got] == ["c1"]


def test_get_unsent_respects_limit_and_order(store: Store) -> None:
    for i in range(5):
        store.ingest("inb1", "conv1", [_event(f"c{i}")], None)
    got = store.get_unsent(3, {"inb1|conv1"})
    assert [m.client_id for m in got] == ["c0", "c1", "c2"]  # by id asc


def test_mark_sent_removes_from_unsent(store: Store) -> None:
    store.ingest("inb1", "conv1", [_event("c1"), _event("c2")], None)
    rows = store.get_unsent(10, {"inb1|conv1"})
    store.mark_sent([rows[0].id])

    assert store.count_unsent() == 1
    remaining = store.get_unsent(10, {"inb1|conv1"})
    assert [m.client_id for m in remaining] == ["c2"]


def test_count_recent_incoming_counts_sent_after_cutoff(store: Store) -> None:
    store.ingest("inb1", "conv1", [_event("c1")], None)
    rows = store.get_unsent(10, {"inb1|conv1"})
    store.mark_sent([rows[0].id])
    # count_recent_incoming only counts sent=1 with sent_at >= cutoff.
    assert store.count_recent_incoming("2026-01-01T00:00:00.000Z") == 1
    assert store.count_recent_incoming("2027-01-01T00:00:00.000Z") == 0


# --------------------------------------------------------------- lifecycle

@pytest.mark.skipif(sys.platform == "win32", reason="flock not used on Windows")
def test_second_open_same_account_raises(tmp_path: Path) -> None:
    db = tmp_path / "acct" / "state.db"
    s = Store(db)
    try:
        with pytest.raises(StoreLockError):
            Store(db)  # flock is held → second open refused
    finally:
        s.close()


def test_schema_version_mismatch_nukes_db(tmp_path: Path) -> None:
    db = tmp_path / "acct" / "state.db"
    s = Store(db)
    s.kv_set("studio_token", "keep-me")
    s.close()

    # Simulate an old on-disk schema by bumping the recorded version.
    conn = sqlite3.connect(str(db))
    conn.execute("UPDATE meta SET version = 999")
    conn.commit()
    conn.close()

    s2 = Store(db)
    try:
        # Mismatch → db nuked and recreated → prior data gone.
        assert s2.kv_get("studio_token") is None
    finally:
        s2.close()


# ----------------------------------------------------- account enumeration

def test_read_account_meta_missing_file(tmp_path: Path) -> None:
    assert read_account_meta(tmp_path / "nope.db") == {}


def test_read_account_meta_reports_token_and_channels(tmp_path: Path) -> None:
    db = tmp_path / "acct" / "state.db"
    s = Store(db)
    s.kv_set("studio_token", "tok")
    s.kv_set("display_name", "Alice")
    s.add_channel("chat", {})
    s.close()

    meta = read_account_meta(db)
    assert meta["has_token"] is True
    assert meta["display_name"] == "Alice"
    assert meta["channel_count"] == 1


def test_list_accounts_sorted_newest_first(tmp_path: Path) -> None:
    for aid in ("acct-old", "acct-new"):
        Store(tmp_path / aid / "state.db").close()

    # close() re-stamps last_active_at with wall-clock at second precision,
    # so it would overwrite anything set via the Store. Write distinct
    # values directly to make the sort deterministic.
    for aid, ts in [("acct-old", "2026-01-01T00:00:00.000Z"),
                    ("acct-new", "2026-12-31T00:00:00.000Z")]:
        conn = sqlite3.connect(str(tmp_path / aid / "state.db"))
        conn.execute("UPDATE kv SET value = ? WHERE key = 'last_active_at'", (ts,))
        conn.commit()
        conn.close()

    accounts = list_accounts(tmp_path)
    assert [a["account_id"] for a in accounts] == ["acct-new", "acct-old"]


def test_list_accounts_empty_root(tmp_path: Path) -> None:
    assert list_accounts(tmp_path / "does-not-exist") == []
