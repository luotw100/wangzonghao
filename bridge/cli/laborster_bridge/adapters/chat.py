"""Chat sandbox adapter.

Login is one-step username+password (single ``PromptInput``). The
adapter then runs purely off the stored credential ``{"token": "..."}``.

Reference implementation of the Adapter Protocol — new platform modules
should follow the same shape: a LoginFlow class, an Adapter class, a
single ``register(AdapterFactory(...))`` at the bottom.
"""

from __future__ import annotations

from datetime import datetime, timezone

from .. import config
from ..http import HttpError, Unauthorized as HttpUnauthorized, request_json
from . import (
    AdapterFactory,
    Conversation,
    Credential,
    Done,
    Failed,
    Field,
    IncomingEvent,
    OutboundPayload,
    PermanentError,
    PromptInput,
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
    """Translate http.* exceptions into the adapter taxonomy."""
    if isinstance(exc, HttpUnauthorized):
        return Unauthorized()
    if isinstance(exc, HttpError):
        return TransientError(str(exc))
    return exc


# ---- login flow -------------------------------------------------------

class _ChatLoginFlow:
    _FIELDS = [
        Field(name="username", label="Chat 用户名"),
        Field(name="password", label="Chat 密码", secret=True),
    ]

    def __init__(self) -> None:
        self._step: Step = PromptInput(title="登录 Chat 沙箱", fields=self._FIELDS)

    def current(self) -> Step:
        return self._step

    def submit(self, answers: dict[str, str]) -> Step:
        if not isinstance(self._step, PromptInput):
            return self._step
        u = (answers.get("username") or "").strip()
        p = answers.get("password") or ""
        if not u or not p:
            self._step = PromptInput(
                title="登录 Chat 沙箱",
                fields=self._FIELDS,
                error="用户名和密码不能为空",
            )
            return self._step
        try:
            r = request_json(
                "POST",
                f"{config.CHAT_BASE_URL}/api/auth/login",
                body={"username": u, "password": p},
            )
        except HttpUnauthorized:
            self._step = PromptInput(
                title="登录 Chat 沙箱",
                fields=self._FIELDS,
                error="账号或密码错误",
            )
            return self._step
        except HttpError as exc:
            raise TransientError(str(exc)) from None
        self._step = Done(credential={"token": r["token"]})
        return self._step

    def poll(self) -> Step:
        # No external-wait step in this flow; nothing to poll.
        return self._step

    def cancel(self) -> None:
        self._step = Failed(reason="用户取消")


# ---- adapter ---------------------------------------------------------

class ChatAdapter:
    def __init__(self, credential: Credential) -> None:
        token = credential.get("token")
        if not isinstance(token, str) or not token:
            raise ValueError("chat credential missing 'token'")
        self._token = token
        self._self_id: str | None = None
        self._self_display: str | None = None

    def _req(self, method: str, path: str, body=None, timeout: float = 20.0):
        try:
            return request_json(
                method,
                f"{config.CHAT_BASE_URL}{path}",
                token=self._token,
                body=body,
                timeout=timeout,
            )
        except (HttpUnauthorized, HttpError) as exc:
            raise _classify(exc) from None

    # ---- identity --------------------------------------------------

    def _ensure_me(self) -> None:
        if self._self_id is None or self._self_display is None:
            me = self._req("GET", "/api/auth/me")
            self._self_id = me["id"]
            self._self_display = me.get("nickname") or me.get("username") or me["id"]

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
        convs = self._req("GET", "/api/conversations")
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
        # Chat's cursor is just the last-seen message id as a string.
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
                f"/api/conversations/{conversation_id}/messages/after"
                f"?last_id={cur}&limit={_SCAN_BATCH}",
            )
            msgs = payload["messages"]
            if not msgs:
                break
            for m in msgs:
                cur = int(m["id"])
                # Chat already encodes "self" as sender_id=NULL; we ship
                # that through unchanged — the wire contract is identical.
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
        # Chat is DM-only; the conversation has exactly one peer. We
        # could cache this across calls, but list_conversations is
        # cheap and the runtime calls it on its own cadence.
        for c in self.list_conversations():
            if c.id == conversation_id:
                return c.peers[0]["platform_id"]
        raise PermanentError(f"unknown conversation {conversation_id}")

    # ---- outbound --------------------------------------------------

    def send(
        self, conversation_id: str, payload: OutboundPayload
    ) -> None:
        if payload.msg_type != "text":
            raise PermanentError(
                f"chat adapter only supports text; got {payload.msg_type!r}"
            )
        # sender_id omitted => recorded as self-sent by the chat server.
        self._req(
            "POST",
            f"/api/conversations/{conversation_id}/messages",
            body={
                "messages": [
                    {"msg_type": "text", "content": payload.content}
                ]
            },
        )


# ---- registration -----------------------------------------------------

register(
    AdapterFactory(
        platform="chat",
        begin_login=lambda: _ChatLoginFlow(),
        build=lambda credential: ChatAdapter(credential),
    )
)
