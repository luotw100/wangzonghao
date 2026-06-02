#!/usr/bin/env bash
# 发版工具的瘦封装。真正的 CLI 在 studio.publish_release（.py，跟镜像走）；本脚本
# 只负责把它跑在 release 栈的 compose 网络里——db(5432)/minio(9000) 只在内网，宿主机
# 够不到，所以工具必须在容器内执行。
#
# 形状同 test.sh / seed.py / backup.sh：env file 在最前，其余参数原样透传给 .py。
# 子命令（publish / list / promote）、校验、版本规则都在 .py 里，脚本不重复。
# 唯一的特殊处理：publish 的 --file 会被自动 bind-mount 进容器（容器看不到你硬盘）。
#
#   scripts/publish-release.sh <env-file> <publish|list|promote> [args...]
#
# 例：
#   scripts/publish-release.sh .env.release list
#   scripts/publish-release.sh .env.release publish \
#       --version 0.1.0 --platform win \
#       --file ~/builds/Laborster-Setup-0.1.0.exe --latest --notes "首个内测版"
#   scripts/publish-release.sh .env.release promote --version 0.0.9 --platform win
#
# 改了 publish_release.py 后要 `up --build` 才生效（工具随镜像走）。
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ENVF="${1:-}"
if [[ -z "$ENVF" ]]; then
  echo "usage: scripts/publish-release.sh <env-file> <publish|list|promote> [args...]" >&2
  echo "       (e.g. scripts/publish-release.sh .env.release list)" >&2
  exit 1
fi
shift
[[ "$ENVF" = /* ]] || ENVF="$ROOT/$ENVF"

# 透传所有参数给 .py；只拦 --file：把本地文件挂进容器，并改写成容器内路径。
mount_args=()
fwd=()
while [[ $# -gt 0 ]]; do
  if [[ "$1" == "--file" ]]; then
    host="${2:?--file 需要一个路径}"
    [[ -f "$host" ]] || { echo "文件不存在: $host" >&2; exit 2; }
    abs="$(realpath "$host")"
    base="$(basename "$abs")"
    mount_args+=(-v "$abs:/in/$base:ro")
    fwd+=(--file "/in/$base")
    shift 2
  else
    fwd+=("$1")
    shift
  fi
done

cd "$ROOT"
exec docker compose --env-file "$ENVF" run --rm --no-deps \
  ${mount_args[@]+"${mount_args[@]}"} \
  user-api uv run python -m studio.publish_release "${fwd[@]}"
