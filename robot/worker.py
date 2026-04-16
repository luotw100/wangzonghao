import argparse
import asyncio
import logging

from robot.db import ensure_database
from robot.runtime import DEFAULT_POLL_INTERVAL, DEFAULT_REQUEST_TIMEOUT, RobotRuntime, RuntimeOptions

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def run_worker(runtime_options: RuntimeOptions):
    runtime = RobotRuntime(runtime_options)
    await runtime.start()
    logger.info("Robot worker started")
    try:
        await asyncio.Event().wait()
    finally:
        await runtime.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Robot worker service")
    parser.add_argument("--chat-api-base-url", required=True)
    parser.add_argument("--request-timeout", type=float, default=DEFAULT_REQUEST_TIMEOUT)
    parser.add_argument("--poll-interval", type=float, default=DEFAULT_POLL_INTERVAL)
    parser.add_argument("--echo-mode", action="store_true")
    return parser.parse_args()


def main():
    ensure_database()
    args = parse_args()
    runtime_options = RuntimeOptions(
        chat_api_base_url=args.chat_api_base_url.rstrip("/"),
        request_timeout=args.request_timeout,
        poll_interval=args.poll_interval,
        echo_mode=args.echo_mode,
    )
    try:
        asyncio.run(run_worker(runtime_options))
    except KeyboardInterrupt:
        logger.info("Robot worker stopped")


if __name__ == "__main__":
    main()