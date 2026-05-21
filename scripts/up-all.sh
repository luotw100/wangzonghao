#!/usr/bin/env bash
# Bring up one isolated instance of the whole stack.
#
#   scripts/up-all.sh <config.json>      e.g. scripts/up-all.sh scripts/.env.debug.json
#
# Service .env files (infra/, services/chat/, services/studio/) are the
# seam — local docker names or cloud URLs, instance-agnostic. The
# instance config (JSON) layered on top carries only the per-instance
# bits inside its `compose` block: COMPOSE_PROJECT_NAME, CF_TUNNEL_TOKEN,
# S3_PUBLIC_URL. The `seed` block is consumed by seed_dev.py only.
set -euo pipefail

# 4 compose files share one project name; each only sees its own
# services, so the others look like "orphans". Silence that warning —
# crucially this also avoids anyone wiring --remove-orphans and nuking
# the sibling services.
export COMPOSE_IGNORE_ORPHANS=true

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

# Render the `compose` block to a tmp KV file: `docker compose --env-file`
# is strictly KEY=VALUE and won't read JSON. We also source it so our
# own COMPOSE_PROJECT_NAME / CF_TUNNEL_TOKEN refs below resolve.
#
# Constraint on compose-block values: plain strings only. No newlines, no
# embedded quotes, no shell-special chars. jq emits values raw — quotes
# would become literal in --env-file, and newlines would corrupt parsing.
# The 3 current keys (project name, CF token, S3 URL) all satisfy this.
TMP_ENV=$(mktemp); trap "rm -f $TMP_ENV" EXIT
jq -r '.compose | to_entries[] | "\(.key)=\(.value)"' "$INST" > "$TMP_ENV"
set -a; source "$TMP_ENV"; set +a
: "${COMPOSE_PROJECT_NAME:?config.compose must set COMPOSE_PROJECT_NAME}"
: "${CF_TUNNEL_TOKEN:?config.compose must set CF_TUNNEL_TOKEN}"
P="$COMPOSE_PROJECT_NAME"

echo ">>> [$P] up infra"
cd "$ROOT/infra"
docker compose -p "$P" --env-file .env --env-file "$TMP_ENV" up --build -d

echo ">>> [$P] up chat"
cd "$ROOT/services/chat"
docker compose -p "$P" --env-file .env --env-file "$TMP_ENV" up --build -d

echo ">>> [$P] up studio"
cd "$ROOT/services/studio"
docker compose -p "$P" --env-file .env --env-file "$TMP_ENV" up --build -d

echo ">>> [$P] up tunnel"
cd "$ROOT/tunnel"
docker compose -p "$P" --env-file "$TMP_ENV" up --build -d

echo ">>> [$P] up"
docker ps --filter "label=com.docker.compose.project=$P" \
  --format 'table {{.Names}}\t{{.Status}}'
