#!/usr/bin/env bash
# Bring up one isolated instance of the merged stack.
#
#   scripts/up-all.sh <config.json>      e.g. scripts/up-all.sh scripts/.env.debug.json
#
# infra/.env carries instance-agnostic seam values (db creds, MinIO creds,
# S3 bucket name). The instance JSON's `compose` block adds the per-instance
# bits (COMPOSE_PROJECT_NAME, CF_TUNNEL_TOKEN, S3_PUBLIC_URL).
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

INST="${1:-}"
if [[ -z "$INST" ]]; then
  echo "usage: scripts/up-all.sh <config.json>   (e.g. scripts/.env.debug.json)" >&2
  exit 1
fi
[[ "$INST" = /* ]] || INST="$ROOT/$INST"
if [[ ! -f "$INST" ]]; then
  echo "config not found: $INST" >&2
  exit 1
fi
jq empty "$INST" 2>/dev/null || { echo "invalid JSON: $INST" >&2; exit 1; }

# Render the `compose` block to a tmp KV file. docker compose --env-file
# is strictly KEY=VALUE so JSON is not directly readable. We also source
# it so COMPOSE_PROJECT_NAME / CF_TUNNEL_TOKEN are visible to this script.
TMP_ENV=$(mktemp); trap "rm -f $TMP_ENV" EXIT
jq -r '.compose | to_entries[] | "\(.key)=\(.value)"' "$INST" > "$TMP_ENV"
set -a; source "$TMP_ENV"; set +a
: "${COMPOSE_PROJECT_NAME:?config.compose must set COMPOSE_PROJECT_NAME}"
: "${CF_TUNNEL_TOKEN:?config.compose must set CF_TUNNEL_TOKEN}"
P="$COMPOSE_PROJECT_NAME"

echo ">>> [$P] up (single compose)"
cd "$ROOT/infra"
docker compose -p "$P" --env-file .env --env-file "$TMP_ENV" up --build -d

docker ps --filter "label=com.docker.compose.project=$P" \
  --format 'table {{.Names}}\t{{.Status}}'
