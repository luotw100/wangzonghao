"""Platform adapter abstraction.

Bridge stays platform-agnostic: runtime/commands only talk to the
:class:`Adapter` Protocol below, never a concrete adapter. Adding a new
platform = drop a module under ``adapters/`` that constructs an
:class:`AdapterFactory` and calls :func:`register`.

Three layers, all platform-neutral:

  AdapterFactory   per platform; advertises platform name, hosts the
                   login flow, builds runtime adapters from credentials.

  LoginFlow        a turn-based state machine the GUI/CLI drives.
                   Yields :class:`Step` values describing what to render
                   or do next. Terminates in ``Done(credential)`` or
                   ``Failed(reason)``. Same shape for password / QR /
                   OAuth / OTP / cookie-injection / anything.

  Adapter          runtime I/O: list_conversations / fetch_new / send.
                   Every method is a single bounded operation (no
                   infinite loops, no internal state to ``stop``).
                   Looping, backoff, supervision belong to the runtime.

Error contract — only four kinds are allowed across this boundary:

  Unauthorized     credential is dead. The channel must rerun
                   ``factory.begin_login()``; siblings are unaffected.

  TransientError   retry with backoff (network drop, 5xx, timeout).

  PermanentError   raised **only** by ``send`` — this specific message
                   is unrecoverable (peer blocked, content rejected);
                   the runtime should ack-failed and move on.

  anything else    a bug. The runtime logs loudly and treats it like a
                   TransientError with a longer backoff; never swallow.

Adapters MUST normalize platform errors into the four kinds above and
MUST keep ``fetch_new`` atomic: return a (possibly empty) list, or
raise; never half-return.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable, Literal, Protocol, TypedDict


# ---- exceptions -------------------------------------------------------

class Unauthorized(Exception):
    """Stored credential is no longer valid; channel needs a fresh login."""


class TransientError(Exception):
    """Operation failed for a recoverable reason; caller should retry."""


class PermanentError(Exception):
    """The specific call cannot be retried; only ``send`` is allowed to raise this."""


# ---- data shapes ------------------------------------------------------

# Credential is a platform-defined JSON-serializable blob. Bridge stores
# and replays it verbatim and never inspects the structure.
Credential = dict[str, Any]


class Peer(TypedDict):
    platform_id: str
    display_name: str


@dataclass(frozen=True)
class Conversation:
    id: str
    kind: Literal["dm", "group"]
    display_name: str
    peers: list[Peer]


@dataclass(frozen=True)
class IncomingEvent:
    conversation_id: str
    client_id: str          # adapter-decided stable id (chat: platform msg.id;
                            # wechat: official msg_id; fallback: adapter hash).
                            # Bridge uses (inbox_id, client_id) for local dedup
                            # AND ships it on wire — Studio dedups by the same
                            # key. There is no separate runtime-side hash.
    sender_id: str | None   # platform id of whoever sent it. None means "self"
                            # (the inbox's platform_self_id sent it).
    sent_at: str            # ISO-ish; opaque to runtime, used for display ordering
    msg_type: str           # text | image | audio | video | file
    content: str
    cursor: str             # adapter-defined; runtime stores it verbatim as the resume point


@dataclass(frozen=True)
class OutboundPayload:
    msg_type: str
    content: str
    media_ref: str | None = None    # storage key for non-text; None for text


# ---- login flow -------------------------------------------------------

@dataclass(frozen=True)
class Field:
    name: str
    label: str
    secret: bool = False
    placeholder: str = ""


@dataclass(frozen=True)
class PromptInput:
    title: str
    fields: list[Field]
    error: str | None = None        # populated on retry after a failed submit


@dataclass(frozen=True)
class WaitForExternal:
    title: str
    poll_after_ms: int = 1500
    qr_png: bytes | None = None
    open_url: str | None = None
    hint: str | None = None


@dataclass(frozen=True)
class Done:
    credential: Credential


@dataclass(frozen=True)
class Failed:
    reason: str


# Type alias for any step; a real protocol implementation would use a
# discriminated union but this keeps GUI/CLI dispatch simple (isinstance).
Step = PromptInput | WaitForExternal | Done | Failed


class LoginFlow(Protocol):
    """Turn-based login state machine.

    Construction may do I/O (raises TransientError) so the first
    ``current()`` is a pure read after the flow exists.
    """

    def current(self) -> Step: ...
    def submit(self, answers: dict[str, str]) -> Step: ...
    def poll(self) -> Step: ...
    def cancel(self) -> None: ...


# ---- adapter ----------------------------------------------------------

class Adapter(Protocol):
    """Runtime I/O for a single channel. Stateless across calls."""

    @property
    def platform_self_id(self) -> str:
        """Platform-stable id of the logged-in account. May lazy-resolve
        on first access (one HTTP) and cache. May raise Unauthorized /
        TransientError on first access only."""
        ...

    @property
    def platform_self_display_name(self) -> str:
        """Platform-side display name of the logged-in account (e.g.
        nickname). Bridge ships it via register_inboxes so Studio can
        show a real name instead of an id. Same lifecycle as
        :attr:`platform_self_id`."""
        ...

    def list_conversations(self) -> list[Conversation]:
        """Current conversation directory. Bounded, single pass."""
        ...

    def fetch_new(
        self, conversation_id: str, since: str | None
    ) -> list[IncomingEvent]:
        """Return events strictly newer than ``since`` for this conversation.

        ``since`` is the ``cursor`` field of the last event the runtime
        successfully ingested for this conversation (or None on first
        fetch). The adapter chooses cursor semantics; the runtime treats
        it as opaque.

        Atomicity: returns a (possibly empty) list or raises; must not
        partially yield events and then raise.
        """
        ...

    def send(
        self, conversation_id: str, payload: OutboundPayload
    ) -> None:
        """Send one message into a conversation. No return value — Studio
        no longer tracks platform_msg_id."""
        ...


# ---- factory + registry ----------------------------------------------

@dataclass(frozen=True)
class AdapterFactory:
    platform: str
    begin_login: Callable[[], LoginFlow]
    build: Callable[[Credential], Adapter]


REGISTRY: dict[str, AdapterFactory] = {}


def register(factory: AdapterFactory) -> None:
    REGISTRY[factory.platform] = factory


def get(platform: str) -> AdapterFactory:
    try:
        return REGISTRY[platform]
    except KeyError:
        raise KeyError(f"unknown platform: {platform}") from None


def platforms() -> list[str]:
    return sorted(REGISTRY)


# Auto-register built-in adapters. Kept at the bottom so the names above
# are bound before submodules import them.
from . import chat as _chat  # noqa: E402,F401
