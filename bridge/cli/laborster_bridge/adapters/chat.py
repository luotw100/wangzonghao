"""Chat sandbox adapter.

After Chat and Studio were merged into a single backend, chat lives at
``${STUDIO_BASE_URL}/api/chat/*`` and there is no separate chat login —
the studio session token authenticates both planes. Chat therefore has
no login flow of its own: ``begin_login`` is degenerate (immediate
``Done({})``) and the adapter reads the *current* ``studio_token`` from
the account store on every request via its CredentialProvider. A Studio
re-login is picked up automatically; no per-channel relogin needed.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .. import config
from ..http import HttpError, Unauthorized as HttpUnauthorized, request_json
from . import (
    AdapterFactory,
    Conversation,
    Credential,
    CredentialProvider,
    Done,
    Failed,
    IncomingEvent,
    OutboundPayload,
    PermanentError,
    Step,
    TransientError,
    Unauthorized,
    register,
)

_SCAN_BATCH = 200


def _iso_z(created_at: str) -> str:
    dt = datetime.fromisoformat(created_at.replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt.strftime("%Y-%m-%dT%H:%M:%S.") + f"{dt.microsecond // 1000:03d}Z"


def _classify(exc: Exception) -> Exception:
    if isinstance(exc, HttpUnauthorized):
        return Unauthorized()
    if isinstance(exc, HttpError):
        return TransientError(str(exc))
    return exc


# ---- login flow -------------------------------------------------------

class _ChatLoginFlow:
    """Degenerate flow: chat inherits Studio's session, so there is
    nothing for the user to do. The credential stored on the channel
    row is an empty marker — the live ``studio_token`` is read from the
    account store on every request via the CredentialProvider.
    """

    def __init__(self) -> None:
        self._step: Step = Done(credential={})

    def current(self) -> Step:
        return self._step

    def submit(self, answers: dict[str, str]) -> Step:
        return self._step

    def poll(self) -> Step:
        return self._step

    def cancel(self) -> None:
        self._step = Failed(reason="用户取消")


# ---- adapter ---------------------------------------------------------

class ChatAdapter:
    """Chat sandbox client. Talks to ``${STUDIO_BASE_URL}/api/chat/*`` for
    chat-specific endpoints and ``/api/auth/me`` for identity (the studio
    account *is* the chat sandbox identity now).

    Holds a CredentialProvider rather than a snapshot. Each request calls
    ``self._provider()`` and pulls ``token`` out — so a Studio re-login
    is picked up on the next request with no relogin step.
    """

    def __init__(self, provider: CredentialProvider) -> None:
        self._provider = provider
        self._self_id: str | None = None
        self._self_display: str | None = None

    def _token(self) -> str:
        cred = self._provider()
        token = cred.get("token") if isinstance(cred, dict) else None
        if not isinstance(token, str) or not token:
            # No studio session → surface as Unauthorized so the worker
            # transitions to NEEDS_LOGIN, prompting a fresh /login.
            raise Unauthorized()
        return token

    def _req(self, method: str, path: str, body=None, timeout: float = 20.0):
        try:
            return request_json(
                method, f"{config.STUDIO_BASE_URL.rstrip('/')}{path}",
                token=self._token(), body=body, timeout=timeout,
            )
        except (HttpUnauthorized, HttpError) as exc:
            raise _classify(exc) from None

    # ---- identity --------------------------------------------------

    def _ensure_me(self) -> None:
        if self._self_id is not None and self._self_display is not None:
            return
        me = self._req("GET", "/api/auth/me")
        self._self_id = me["id"]
        # Studio account uses display_name; fall back to username so the
        # inbox always has a non-empty label.
        self._self_display = me.get("display_name") or me.get("username") or me["id"]

    @property
    def platform_self_id(self) -> str:
        self._ensure_me()
        assert self._self_id is not None
        return self._self_id

    @property
    def platform_self_display_name(self) -> str:
        self._ensure_me()
        assert self._self_display is not None
        return self._self_display

    # ---- directory -------------------------------------------------

    def list_conversations(self) -> list[Conversation]:
        convs = self._req("GET", "/api/chat/conversations")
        out: list[Conversation] = []
        for c in convs:
            contact = c["contact"]
            display = contact.get("nickname") or contact.get("username") or contact["id"]
            out.append(
                Conversation(
                    id=c["id"],
                    kind="dm",
                    display_name=display,
                    peers=[{"platform_id": contact["id"], "display_name": display}],
                )
            )
        return out

    # ---- inbound ---------------------------------------------------

    def fetch_new(
        self, conversation_id: str, since: str | None
    ) -> list[IncomingEvent]:
        try:
            last_id = int(since) if since else 0
        except (TypeError, ValueError):
            last_id = 0

        gathered: list[IncomingEvent] = []
        peer_id = self._peer_for(conversation_id)
        cur = last_id
        while True:
            payload = self._req(
                "GET",
                f"/api/chat/conversations/{conversation_id}/messages/after"
                f"?last_id={cur}&limit={_SCAN_BATCH}",
            )
            msgs = payload["messages"]
            if not msgs:
                break
            for m in msgs:
                cur = int(m["id"])
                sender_id = None if m["sender_id"] is None else peer_id
                gathered.append(
                    IncomingEvent(
                        conversation_id=conversation_id,
                        client_id=str(m["id"]),
                        sender_id=sender_id,
                        sent_at=_iso_z(m["created_at"]),
                        msg_type=m.get("msg_type") or "text",
                        content=m["content"],
                        cursor=str(m["id"]),
                    )
                )
            if len(msgs) < _SCAN_BATCH:
                break
        return gathered

    def _peer_for(self, conversation_id: str) -> str:
        for c in self.list_conversations():
            if c.id == conversation_id:
                return c.peers[0]["platform_id"]
        raise PermanentError(f"unknown conversation {conversation_id}")

    # ---- outbound --------------------------------------------------

    def send(self, conversation_id: str, payload: OutboundPayload) -> None:
        if payload.msg_type != "text":
            raise PermanentError(
                f"chat adapter only supports text; got {payload.msg_type!r}"
            )
        self._req(
            "POST",
            f"/api/chat/conversations/{conversation_id}/messages",
            body={"messages": [{"msg_type": "text", "content": payload.content}]},
        )


# ---- registration -----------------------------------------------------

def _chat_make_provider(_credential: Credential, store) -> CredentialProvider:
    """Chat inherits Studio's session: each request reads the *current*
    ``studio_token`` from the account store. The stored channel credential
    is empty — nothing per-channel to snapshot.
    """
    return lambda: {"token": store.kv_get("studio_token") if store else None}


register(
    AdapterFactory(
        platform="chat",
        begin_login=lambda: _ChatLoginFlow(),
        build=lambda provider: ChatAdapter(provider),
        make_provider=_chat_make_provider,
    )
)
