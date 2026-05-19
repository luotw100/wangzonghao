#!/usr/bin/env bash
# Stop one instance of the stack.
#
#   scripts/down-all.sh <instance-file>       stop, KEEP volumes
#   scripts/down-all.sh <instance-file> -v    stop and DELETE this
#                                             instance's volumes (data loss)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

INST="${1:-}"
WIPE="${2:-}"
if [[ -z "$INST" ]]; then
  echo "usage: scripts/down-all.sh <instance-file> [-v]" >&2
  exit 1
fi
[[ "$INST" = /* ]] || INST="$ROOT/$INST"
if [[ ! -f "$INST" ]]; then
  echo "instance file not found: $INST" >&2
  exit 1
fi

set -a; source "$INST"; set +a
: "${COMPOSE_PROJECT_NAME:?instance file must set COMPOSE_PROJECT_NAME}"
P="$COMPOSE_PROJECT_NAME"

V=""
if [[ "$WIPE" == "-v" ]]; then
  read -r -p "DELETE all volumes (data) for instance '$P'? [y/N] " ans
  [[ "$ans" == "y" || "$ans" == "Y" ]] || { echo "aborted"; exit 1; }
  V="--volumes"
fi

echo ">>> [$P] down tunnel"
cd "$ROOT/tunnel"
docker compose -p "$P" --env-file "$INST" down $V

echo ">>> [$P] down studio"
cd "$ROOT/services/studio"
docker compose -p "$P" --env-file .env --env-file "$INST" down $V

echo ">>> [$P] down chat"
cd "$ROOT/services/chat"
docker compose -p "$P" --env-file .env --env-file "$INST" down $V

echo ">>> [$P] down infra"
cd "$ROOT/infra"
docker compose -p "$P" --env-file .env --env-file "$INST" down $V

if [[ "$WIPE" == "-v" ]]; then
  echo ">>> [$P] stopped, volumes deleted"
else
  echo ">>> [$P] stopped (volumes kept; pass -v to delete)"
fi
