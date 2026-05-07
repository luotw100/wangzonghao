import argparse
import asyncio
import logging

from studio.db import ensure_database
from studio.runtime import StudioRuntime, RuntimeOptions

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


async def run_worker(runtime_options: RuntimeOptions):
    runtime = StudioRuntime(runtime_options)
    await runtime.start()
    logger.info("Studio worker started")
    try:
        await asyncio.Event().wait()
    finally:
        await runtime.stop()


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the Studio worker service")
    parser.add_argument("--request-timeout", type=float, required=True,
                        help="LLM 请求超时秒数，例: 120")
    return parser.parse_args()


def main():
    ensure_database()
    args = parse_args()
    runtime_options = RuntimeOptions(request_timeout=args.request_timeout)
    try:
        asyncio.run(run_worker(runtime_options))
    except KeyboardInterrupt:
        logger.info("Studio worker stopped")


if __name__ == "__main__":
    main()
