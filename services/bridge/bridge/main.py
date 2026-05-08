"""Bridge daemon entry point.

No persistent token. The daemon authenticates against Studio with the
streamer's Studio account credentials (the same login used in the web UI)
plus the local hostname; Studio auto-provisions a Bridge row keyed by
(account, hostname) and mints a fresh session token at every handshake.

    bridge \\
      --studio-username=alice \\
      --studio-password=... \\
      --chat-inbox 'base_url=https://chat.laborster.com,username=alice,password=...' \\
      --chat-inbox 'base_url=https://chat.laborster.com,username=alice2,password=...'

Pass --studio-url to point at a non-prod Studio (defaults to the cloud).
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

DEFAULT_STUDIO_URL = "https://studio.laborster.com"


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
    p.add_argument("--studio-username", required=True,
                   help="Your Studio account username (same as the web login).")
    p.add_argument("--studio-password", required=True,
                   help="Your Studio account password.")
    p.add_argument("--studio-url", default=DEFAULT_STUDIO_URL,
                   help=f"Studio base URL (default: {DEFAULT_STUDIO_URL}).")
    p.add_argument("--hostname", default=None,
                   help="Identifier for this PC (defaults to socket.gethostname()).")
    p.add_argument(
        "--chat-inbox", action="append", default=[], dest="chat_inboxes",
        help="Repeat for each chat account, e.g. "
             "--chat-inbox 'base_url=...,username=...,password=...'",
    )
    return p


async def _run(
    *,
    studio_url: str,
    username: str,
    password: str,
    hostname: str,
    claims: List[InboxClaim],
) -> None:
    if not claims:
        logger.warning("no --chat-inbox given; bridge will idle (only heartbeats).")
    studio = StudioClient(
        base_url=studio_url, username=username, password=password,
    )
    runtime = BridgeRuntime(studio=studio, hostname=hostname, claims=claims)
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
    claims: List[InboxClaim] = [
        InboxClaim(platform="chat", raw=_parse_chat_inbox(spec))
        for spec in args.chat_inboxes
    ]
    hostname = args.hostname or socket.gethostname()
    try:
        asyncio.run(_run(
            studio_url=args.studio_url,
            username=args.studio_username,
            password=args.studio_password,
            hostname=hostname,
            claims=claims,
        ))
    except KeyboardInterrupt:
        logger.info("bridge stopped (KeyboardInterrupt)")
        sys.exit(0)


if __name__ == "__main__":
    main()
