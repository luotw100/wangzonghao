"""Bridge daemon entry point.

Zero config files. Everything is on the CLI:

    bridge \\
      --token=BRIDGE_TOKEN \\
      --chat-inbox 'base_url=https://chat.laborster.com,username=alice,password=...' \\
      --chat-inbox 'base_url=https://chat.laborster.com,username=alice2,password=...'

The Studio URL is hardcoded; the daemon never needs to know any inbox_id —
each `--chat-inbox` is just a chat platform login. Studio resolves
`(platform, platform_self_id)` to its own internal inbox_id during handshake
and auto-creates an Inbox row if one doesn't exist yet.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import signal
import socket
import sys
from typing import Dict, List

# Side-effect imports: adapters call register_adapter() at module load.
import bridge.adapters.chat  # noqa: F401

from bridge.runtime import BridgeRuntime, InboxClaim
from bridge.studio_client import StudioClient

logger = logging.getLogger("bridge")

STUDIO_URL = "https://studio.laborster.com"


def _parse_chat_inbox(raw: str) -> Dict[str, str]:
    """Parse 'key=value,key=value,...' into a dict.

    No URL-encoding; values cannot contain commas. Passwords with commas
    are unsupported (regenerate the password if you hit this).
    """
    out: Dict[str, str] = {}
    for part in raw.split(","):
        part = part.strip()
        if not part:
            continue
        if "=" not in part:
            raise SystemExit(f"--chat-inbox segment missing '=': {part!r}")
        k, v = part.split("=", 1)
        out[k.strip()] = v.strip()
    for required in ("base_url", "username", "password"):
        if not out.get(required):
            raise SystemExit(f"--chat-inbox missing {required!r}: {raw!r}")
    return out


def _build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="bridge",
        description="Laborster Bridge daemon. Connects local chat platform "
                    "logins to Studio.",
    )
    p.add_argument("--token", required=True, help="Bridge token from Studio.")
    p.add_argument(
        "--chat-inbox", action="append", default=[], dest="chat_inboxes",
        help="Repeat for each chat account, e.g. "
             "--chat-inbox 'base_url=...,username=...,password=...'",
    )
    return p


async def _run(claims: List[InboxClaim]) -> None:
    if not claims:
        logger.warning("no --chat-inbox given; bridge will idle (only heartbeats).")
    studio = StudioClient(base_url=STUDIO_URL, token=os.environ["BRIDGE_TOKEN"])
    runtime = BridgeRuntime(
        studio=studio,
        hostname=socket.gethostname(),
        claims=claims,
    )
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, runtime.stop)
    try:
        await runtime.run()
    finally:
        await studio.close()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    args = _build_arg_parser().parse_args()
    os.environ["BRIDGE_TOKEN"] = args.token  # avoid leaking via argv to subprocesses
    claims: List[InboxClaim] = [
        InboxClaim(platform="chat", raw=_parse_chat_inbox(spec))
        for spec in args.chat_inboxes
    ]
    try:
        asyncio.run(_run(claims))
    except KeyboardInterrupt:
        logger.info("bridge stopped (KeyboardInterrupt)")
        sys.exit(0)


if __name__ == "__main__":
    main()
