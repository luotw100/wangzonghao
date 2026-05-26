#!/usr/bin/env bash
# Run the API test suite against an already-running instance.
#
#   scripts/test.sh <config.json> [pytest args...]
#
# Example: scripts/test.sh scripts/.env.debug.json -k test_auth
#
# Assumes the stack is already up (scripts/up-all.sh <config.json>).
# Tests live in the api image (tests/ is COPY'd in), so --build re-bakes
# only the tests layer when test code changes — other layers stay cached.
#
# Self-cleaning: on exit (success, failure, Ctrl-C) the test-runner and
# fake-llm containers are removed and the test image is dropped, so the
# next run starts from a clean slate without touching the long-running
# user-api/user-worker/admin-api stack.
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

TMP_ENV=$(mktemp); trap "rm -f $TMP_ENV" EXIT
jq -r '.compose | to_entries[] | "\(.key)=\(.value)"' "$INST" > "$TMP_ENV"
set -a; source "$TMP_ENV"; set +a
: "${COMPOSE_PROJECT_NAME:?config.compose must set COMPOSE_PROJECT_NAME}"
P="$COMPOSE_PROJECT_NAME"

COMPOSE=(docker compose -f "$ROOT/docker-compose.yaml" -p "$P"
         --env-file "$ROOT/.env" --env-file "$TMP_ENV"
         --profile test)

cleanup() {
  echo ">>> [$P] cleaning up fake-llm + test-runner"
  "${COMPOSE[@]}" rm -fsv fake-llm test-runner >/dev/null 2>&1 || true
}
trap cleanup EXIT INT TERM

if [[ "$#" -eq 0 ]]; then
  set -- tests/ -x -v
fi

echo ">>> [$P] running tests"
"${COMPOSE[@]}" run --build --rm test-runner "$@"
