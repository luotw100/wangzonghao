"""Entry point.

Two modes:

  * Interactive (default): REPL on stdin. The packaged GUI binary and
    operator CLI use this path — see :mod:`laborster_bridge.repl`.
  * Headless (``--headless``): hosted-bridge subprocess spawned by the
    cloud-side ``bridge-host`` service. No REPL, no password prompts;
    token + machine_id are passed in by admin-api. See
    :mod:`laborster_bridge.headless`.

End-user binaries never pass ``--headless`` or ``--studio-url``; those
flags exist exclusively for the hosted-bridge path.
"""

from __future__ import annotations

import argparse
import sys

from . import config, repl


def main() -> int:
    parser = argparse.ArgumentParser(prog="laborster-bridge")
    parser.add_argument("--state", metavar="DIR", help="状态目录（无默认值）")
    parser.add_argument(
        "--headless", action="store_true",
        help="hosted-bridge 模式：无 REPL，由 bridge-host 启动"
    )
    parser.add_argument("--studio-url", help="Studio base URL（仅 headless）")
    parser.add_argument("--account-id", help="Studio account id（仅 headless）")
    parser.add_argument("--token", help="Studio session token（仅 headless）")
    parser.add_argument("--machine-id", help="Bridge machine_id（仅 headless）")
    parser.add_argument(
        "--display-name", default="",
        help="账号显示名，仅作为 store kv 中的渲染缓存"
    )
    args = parser.parse_args()

    if args.headless:
        missing = [
            f for f in ("state", "studio_url", "account_id", "token", "machine_id")
            if not getattr(args, f)
        ]
        if missing:
            print(
                "--headless 缺参数: " + ", ".join("--" + m.replace("_", "-") for m in missing),
                file=sys.stderr,
            )
            return 3
        from . import headless
        return headless.run(args)

    if args.state:
        try:
            config.set_state_root(args.state)
        except Exception as exc:
            print(f"--state 无效: {exc}", file=sys.stderr)
            return 2
    # Non-headless = end-user binary: learn the live API host from discovery
    # (headless got its URL from --studio-url above and must not do this).
    config.resolve_studio_base_url()
    return repl.run()


if __name__ == "__main__":
    raise SystemExit(main())
