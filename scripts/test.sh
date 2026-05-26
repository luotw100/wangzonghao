#!/usr/bin/env bash
# Run the API test suite inside the already-running user-api container.
#
#   scripts/test.sh <config.json> [pytest args...]
#
# Tests are baked into the api image (Dockerfile COPY tests). fake-llm
# is a regular long-running service on the same network. To pick up
# test/source changes, re-run scripts/up-all.sh — that's the only
# build step in the loop.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

INST="${1:-}"
if [[ -z "$INST" ]]; then
  echo "usage: scripts/test.sh <config.json> [pytest args...]" >&2
  exit 1
fi
shift
[[ "$INST" = /* ]] || INST="$ROOT/$INST"
if [[ ! -f "$INST" ]]; then
  echo "config not found: $INST" >&2
  exit 1
fi

P=$(jq -r '.compose.COMPOSE_PROJECT_NAME' "$INST")
: "${P:?config.compose.COMPOSE_PROJECT_NAME missing}"

if [[ "$#" -eq 0 ]]; then
  set -- tests/ -x -v
fi

exec docker compose -p "$P" exec user-api uv run python -m pytest "$@"
