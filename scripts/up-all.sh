#!/usr/bin/env bash
# Bring up one isolated instance of the whole stack.
#
#   scripts/up-all.sh <instance-file>      e.g. scripts/up-all.sh .env.ver1
#
# Service .env files (infra/, services/chat/, services/studio/) are the
# seam — local docker names or cloud URLs, instance-agnostic. The
# instance file layered on top carries only the per-instance bits:
#   COMPOSE_PROJECT_NAME, CF_TUNNEL_TOKEN, S3_PUBLIC_URL (verN.*)
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
  echo "usage: scripts/up-all.sh <instance-file>   (e.g. .env.ver1)" >&2
  exit 1
fi
[[ "$INST" = /* ]] || INST="$ROOT/$INST"
if [[ ! -f "$INST" ]]; then
  echo "instance file not found: $INST" >&2
  exit 1
fi

set -a; source "$INST"; set +a
: "${COMPOSE_PROJECT_NAME:?instance file must set COMPOSE_PROJECT_NAME}"
: "${CF_TUNNEL_TOKEN:?instance file must set CF_TUNNEL_TOKEN}"
P="$COMPOSE_PROJECT_NAME"

echo ">>> [$P] up infra"
cd "$ROOT/infra"
docker compose -p "$P" --env-file .env --env-file "$INST" up --build -d

echo ">>> [$P] up chat"
cd "$ROOT/services/chat"
docker compose -p "$P" --env-file .env --env-file "$INST" up --build -d

echo ">>> [$P] up studio"
cd "$ROOT/services/studio"
docker compose -p "$P" --env-file .env --env-file "$INST" up --build -d

echo ">>> [$P] up tunnel"
cd "$ROOT/tunnel"
docker compose -p "$P" --env-file "$INST" up --build -d

echo ">>> [$P] up"
docker ps --filter "label=com.docker.compose.project=$P" \
  --format 'table {{.Names}}\t{{.Status}}'
