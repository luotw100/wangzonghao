#!/usr/bin/env bash
# Run the API test suite inside the already-running user-api container.
#
#   scripts/test.sh .env.debug [pytest args...]
#
# Only COMPOSE_PROJECT_NAME is read from the env file — the container is
# located by project, so no -f / profiles needed. Tests are baked into the
# api image (Dockerfile COPY tests); fake-llm is a long-running service on
# the same network. To pick up test/source changes, rebuild the app:
#   docker compose --env-file .env.debug up -d --build
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

ENVF="${1:-}"
if [[ -z "$ENVF" ]]; then
  echo "usage: scripts/test.sh <env-file> [pytest args...]   (e.g. scripts/test.sh .env.debug)" >&2
  exit 1
fi
shift
[[ "$ENVF" = /* ]] || ENVF="$ROOT/$ENVF"
if [[ ! -f "$ENVF" ]]; then
  echo "env file not found: $ENVF" >&2
  exit 1
fi

set -a; . "$ENVF"; set +a
: "${COMPOSE_PROJECT_NAME:?env file must set COMPOSE_PROJECT_NAME}"

if [[ "$#" -eq 0 ]]; then
  set -- tests/ -x -v
fi

exec docker compose -p "$COMPOSE_PROJECT_NAME" exec user-api uv run python -m pytest "$@"
