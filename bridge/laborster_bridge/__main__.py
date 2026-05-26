"""Entry point. Optional --state pre-sets the state directory.

Double-clicking the packaged binary passes no args, so the CLI starts in
no-state mode and the user runs /state <path>. There is deliberately no
default location and no environment variable.
"""

from __future__ import annotations

import argparse
import sys

from . import config, repl


def main() -> int:
    parser = argparse.ArgumentParser(prog="laborster-bridge")
    parser.add_argument("--state", metavar="DIR", help="状态目录（无默认值）")
    args = parser.parse_args()
    if args.state:
        try:
            config.set_state_root(args.state)
        except Exception as exc:
            print(f"--state 无效: {exc}", file=sys.stderr)
            return 2
    return repl.run()


if __name__ == "__main__":
    raise SystemExit(main())
