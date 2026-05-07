"""Bridge daemon entry point.

Reads its config from a TOML file (default ~/.bridge/config.toml). The
file enumerates the daemon's Studio token and the inboxes it knows how
to serve, with platform-specific credentials per inbox.

Usage:
    BRIDGE_CONFIG=/path/to/bridge.toml uv run python -m bridge.main

See bridge/config.py for the file format.

Adapters self-register via side-effect import; we list them explicitly
here so the registry is populated regardless of config order.
"""

from __future__ import annotations

import asyncio
import logging
import os
import signal
import sys

# Side-effect imports: adapters call register_adapter() at module load.
import bridge.adapters.chat  # noqa: F401

from bridge.config import default_config_path, load_config
from bridge.runtime import BridgeRuntime
from bridge.studio_client import StudioClient

logger = logging.getLogger("bridge")


async def _run() -> None:
    cfg_path = default_config_path()
    logger.info("loading config from %s", cfg_path)
    cfg = load_config(cfg_path)
    studio = StudioClient(base_url=cfg.studio_url, token=cfg.token)
    runtime = BridgeRuntime(studio=studio, config=cfg)

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
    try:
        asyncio.run(_run())
    except KeyboardInterrupt:
        logger.info("bridge stopped (KeyboardInterrupt)")
        sys.exit(0)


if __name__ == "__main__":
    main()
