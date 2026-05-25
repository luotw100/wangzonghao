#!/usr/bin/env bash
# Stop one instance of the merged stack.
#
#   scripts/down-all.sh <config.json>       stop, KEEP volumes
#   scripts/down-all.sh <config.json> -v    stop and DELETE volumes (data loss)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

INST="${1:-}"
WIPE="${2:-}"
if [[ -z "$INST" ]]; then
  echo "usage: scripts/down-all.sh <config.json> [-v]" >&2
  exit 1
fi
[[ "$INST" = /* ]] || INST="$ROOT/$INST"
if [[ ! -f "$INST" ]]; then
  echo "config not found: $INST" >&2
  exit 1
fi
jq empty "$INST" 2>/dev/null || { echo "invalid JSON: $INST" >&2; exit 1; }

TMP_ENV=$(mktemp); trap "rm -f $TMP_ENV" EXIT
jq -r '.compose | to_entries[] | "\(.key)=\(.value)"' "$INST" > "$TMP_ENV"
set -a; source "$TMP_ENV"; set +a
: "${COMPOSE_PROJECT_NAME:?config.compose must set COMPOSE_PROJECT_NAME}"
P="$COMPOSE_PROJECT_NAME"

V=""
if [[ "$WIPE" == "-v" ]]; then
  read -r -p "DELETE all volumes (data) for instance '$P'? [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || { echo "aborted"; exit 1; }
  V="--volumes"
fi

echo ">>> [$P] down"
cd "$ROOT/infra"
docker compose -p "$P" --env-file .env --env-file "$TMP_ENV" down $V

if [[ "$WIPE" == "-v" ]]; then
  echo ">>> [$P] stopped, volumes deleted"
else
  echo ">>> [$P] stopped (volumes kept; pass -v to delete)"
fi
