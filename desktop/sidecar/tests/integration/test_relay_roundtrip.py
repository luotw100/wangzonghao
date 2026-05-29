"""sidecar StudioClient ↔ a live Studio: the full relay round-trip, no mocks.

These exercise the bridge's OWN client code (laborster_bridge.studio_client)
against a running user-api — handshake, inbox registration, conversation +
message push, dedup, outbound long-poll. Studio-side correctness is covered
by services/api/tests/bridge; here we prove the sidecar speaks the protocol
correctly end to end.

Skipped unless STUDIO_BASE_URL + ADMIN_BASE_URL are set (see conftest).
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone

import pytest

from laborster_bridge.studio_client import StudioClient

pytestmark = pytest.mark.skipif(
    not (os.environ.get("STUDIO_BASE_URL") and os.environ.get("ADMIN_BASE_URL")),
    reason="live stack only: set STUDIO_BASE_URL + ADMIN_BASE_URL",
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _handshake(account: dict) -> StudioClient:
    """Run the real handshake; return a client carrying the minted creds."""
    boot = StudioClient(get_token=lambda: None)
    hs = boot.handshake(account["username"], account["password"], None)
    assert hs["account_id"] == account["id"]
    assert len(hs["machine_id"]) == 4  # Studio mints a 4-char machine id
    token, machine_id = hs["token"], hs["machine_id"]
    return StudioClient(get_token=lambda: token, get_machine_id=lambda: machine_id)


def _register_inbox(client: StudioClient) -> str:
    self_id = f"selfid-{uuid.uuid4().hex[:8]}"
    inboxes = client.register_inboxes(
        [{"platform": "chat", "platform_self_id": self_id, "display_name": "me"}]
    )
    assert len(inboxes) == 1
    return inboxes[0]["id"]


def test_handshake_and_inbox_registration(account):
    client = _handshake(account)
    self_id = f"selfid-{uuid.uuid4().hex[:8]}"
    claim = {"platform": "chat", "platform_self_id": self_id, "display_name": "me"}

    first = client.register_inboxes([claim])
    assert first[0]["platform"] == "chat"
    assert first[0]["platform_self_id"] == self_id

    # Registration is idempotent: same claim → same inbox id.
    again = client.register_inboxes([claim])
    assert again[0]["id"] == first[0]["id"]

    # The authoritative set reflects the binding.
    assert any(i["platform_self_id"] == self_id for i in client.get_inboxes())

    client.heartbeat()  # authed call must not raise


def test_incoming_roundtrip_and_dedup(account):
    client = _handshake(account)
    inbox_id = _register_inbox(client)

    pcid = f"pc-{uuid.uuid4().hex[:8]}"
    client.push_conversations(
        inbox_id,
        [{
            "platform_conversation_id": pcid,
            "kind": "dm",
            "display_name": "peer",
            "members": [{"peer_platform_id": "peer-x", "display_name": "X"}],
        }],
    )

    msg = {
        "inbox_id": inbox_id,
        "platform_conversation_id": pcid,
        "client_id": f"cid-{uuid.uuid4().hex}",
        "sender_id": "peer-x",
        "msg_type": "text",
        "content": "hello from peer",
        "sent_at": _now_iso(),
    }
    assert client.push_incoming([msg]) == {"accepted": 1, "deduped": 0, "rejected": 0}
    # Re-pushing the same client_id is idempotent server-side.
    assert client.push_incoming([msg]) == {"accepted": 0, "deduped": 1, "rejected": 0}


def test_outbound_longpoll_empty_returns_quickly(account):
    client = _handshake(account)
    _register_inbox(client)
    # Nothing queued → long-poll returns [] without hanging the full timeout.
    assert client.get_outbound(timeout_secs=1) == []
