#!/usr/bin/env bash
# 发版：把本地桌面安装包上传到 release 栈的 S3，并登记到 releases 表、设为该平台 latest。
# 安装包来自 desktop/ 的构建产物（Win x64 .exe / Mac arm64 .dmg）。表无数据前
# /api/download/latest 返回 404；publish 后即对外可下。
#
# 用法：
#   scripts/publish-release.sh <version> <win|mac> <安装包路径> [发布说明]
# 例：
#   scripts/publish-release.sh 0.1.0 win  ~/builds/Laborster-Setup-0.1.0.exe "首个内测版"
#   scripts/publish-release.sh 0.1.0 mac  ~/builds/Laborster-0.1.0-arm64.dmg
#
# 查看 / 回滚（不重传，直接切 latest 指针）：
#   ENV_FILE=.env.release scripts/publish-release.sh --list
#   ENV_FILE=.env.release scripts/publish-release.sh --promote 0.1.0 win
#
# 覆盖实例：ENV_FILE=.env.debug scripts/publish-release.sh ...
set -euo pipefail

ENV_FILE="${ENV_FILE:-.env.release}"
cd "$(dirname "$0")/.."

run() {
  docker compose --env-file "$ENV_FILE" run --rm --no-deps "$@"
}

case "${1:-}" in
  --list)
    run user-api uv run python -m studio.publish_release list
    ;;
  --promote)
    VERSION="${2:?用法: --promote <version> <win|mac>}"
    PLATFORM="${3:?platform 必须是 win 或 mac}"
    run user-api uv run python -m studio.publish_release promote \
      --version "$VERSION" --platform "$PLATFORM"
    ;;
  "" | -h | --help)
    sed -n '2,17p' "$0"
    ;;
  *)
    VERSION="$1"
    PLATFORM="${2:?platform 必须是 win 或 mac}"
    FILE="${3:?需要安装包路径}"
    NOTES="${4:-}"
    [[ "$PLATFORM" == "win" || "$PLATFORM" == "mac" ]] || { echo "platform 必须是 win 或 mac" >&2; exit 2; }
    [[ -f "$FILE" ]] || { echo "文件不存在: $FILE" >&2; exit 2; }
    ABS="$(realpath "$FILE")"
    BASE="$(basename "$ABS")"
    run -v "$ABS":/in/"$BASE":ro \
      user-api uv run python -m studio.publish_release publish \
      --version "$VERSION" --platform "$PLATFORM" --file /in/"$BASE" --latest \
      ${NOTES:+--notes "$NOTES"}
    ;;
esac
