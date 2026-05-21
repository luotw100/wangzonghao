"""Platform adapter registry.

Bridge stays platform-agnostic: runtime and commands only talk to the
:class:`Adapter` protocol below, never to a concrete adapter. Adding a
new inbox platform = drop a module under ``adapters/`` that constructs
an :class:`AdapterFactory` and calls :func:`register`. Nothing in
``runtime.py``, ``commands.py``, or the Studio protocol changes.

Adapter contract (the 5 methods every adapter must implement):

  resolve_self()         -> str
      One-shot. Resolve the platform's self id from the stored token.

  list_peers()           -> list[dict]
      Return the current conversation directory:
      [{"peer_platform_id": ..., "display_name": ...}, ...]

  scan(cursors)          -> Iterator[dict]
      Yield incoming messages forever. Must be reentrant — runtime may
      restart it with the same ``cursors`` dict after an exception.
      Must advance ``cursors[peer_id]`` monotonically. Each yielded
      message has shape:
        peer_id, peer_display_name, platform_msg_id (str|None),
        sender_id, msg_type, content,
        sent_at (str — opaque to bridge; Studio re-canonicalizes)

  send(peer_id, content) -> str
      Send a text message. Return the platform msg id if the platform
      gives one back synchronously, else "".

  stop()                 -> None
      Signal scan() to exit.

Required on the factory (called outside the runtime loop):

  factory.obtain_token(username, password) -> (token, self_id)
      One-shot credential exchange used by ``/channel add``. May raise
      :class:`laborster_bridge.http.Unauthorized` or HttpError.

  factory.build(token, label) -> Adapter
      Construct an adapter from a stored token.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Iterator, Protocol


class Adapter(Protocol):
    @property
    def platform_self_id(self) -> str: ...

    def resolve_self(self) -> str: ...
    def list_peers(self) -> list[dict]: ...
    def scan(self, cursors: dict[str, str | None]) -> Iterator[dict]: ...
    def send(self, peer_id: str, content: str) -> str: ...
    def stop(self) -> None: ...


@dataclass(frozen=True)
class AdapterFactory:
    platform: str
    build: Callable[[str, str], Adapter]
    obtain_token: Callable[[str, str], tuple[str, str]]


REGISTRY: dict[str, AdapterFactory] = {}


def register(factory: AdapterFactory) -> None:
    REGISTRY[factory.platform] = factory


def get(platform: str) -> AdapterFactory:
    try:
        return REGISTRY[platform]
    except KeyError:
        raise KeyError(f"unknown platform: {platform}") from None


# Auto-register built-in adapters. Kept at the bottom so the names
# above are bound before submodules import them.
from . import chat as _chat  # noqa: E402,F401
