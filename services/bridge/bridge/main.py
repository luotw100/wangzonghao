"""Bridge daemon entry point.

Configuration via env vars (set in docker compose / `.env`):

    ROBOT_URL           e.g. http://robot-api:23457
    BRIDGE_TOKEN        b_token issued by Robot when the inbox was created
    BRIDGE_HOSTNAME     human-readable label, defaults to socket.gethostname()
    PLATFORM            'chat' (only one supported in v1)
    CHAT_BASE_URL       e.g. http://chat-api:23456 (when PLATFORM=chat)
    CHAT_USERNAME       chat account username (this is the streamer's chat login)
    CHAT_PASSWORD       chat account password
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import socket
import sys
from typing import Optional

from bridge.adapters.base import Adapter
from bridge.adapters.chat import ChatAdapter
from bridge.robot_client import RobotClient
from bridge.runtime import BridgeRuntime, RuntimeOptions

logger = logging.getLogger("bridge")


def _required(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise SystemExit(f"missing required env: {name}")
    return v


def _build_adapter(platform: str) -> Adapter:
    if platform == "chat":
        return ChatAdapter(
            base_url=_required("CHAT_BASE_URL"),
            username=_required("CHAT_USERNAME"),
            password=_required("CHAT_PASSWORD"),
        )
    raise SystemExit(f"unsupported platform: {platform}")


async def _run() -> None:
    robot_url = _required("ROBOT_URL")
    b_token = _required("BRIDGE_TOKEN")
    platform = _required("PLATFORM")
    hostname = os.environ.get("BRIDGE_HOSTNAME") or socket.gethostname()

    adapter = _build_adapter(platform)
    robot = RobotClient(base_url=robot_url, b_token=b_token)
    runtime = BridgeRuntime(
        robot=robot, adapter=adapter, options=RuntimeOptions(hostname=hostname),
    )

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        loop.add_signal_handler(sig, runtime.stop)

    try:
        await runtime.run()
    finally:
        await adapter.close()
        await robot.close()


def main() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("bridge stopped (KeyboardInterrupt)")
        sys.exit(0)


if __name__ == "__main__":
    main()
