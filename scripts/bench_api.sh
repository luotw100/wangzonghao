#!/usr/bin/env bash
# Read-only single-endpoint capacity benchmark for the studio/chat GET routes.
#
# Same shape as loadtest.py / seed.py / backup.sh / test.sh: env file first.
# The project name is read from the env file's COMPOSE_PROJECT_NAME, and the
# user-api / admin-api container IPs are resolved live from compose labels — on
# Linux the host routes straight to the container, so no published port and no
# edge profile are needed. Bring the instance up with just the local profiles:
#
#   docker compose --env-file .env.debug --profile storage --profile app up -d
#
# Self-contained: mints one throwaway account via the (unauthenticated)
# admin-api, logs in, auto-discovers a real id for each {param} detail route
# from its list route, probes each endpoint (only 200s get benchmarked, so
# routes needing other auth — bridge/* — or empty media keys are auto-skipped),
# then runs wrk with the Bearer token. Read-only: never mutates studio/chat data.
#
# A throwaway account starts with empty lists, so the {id} detail routes SKIP;
# the list routes (auth/me, inboxes, conversations, …) still 200 and benchmark.
#
# Usage:
#   scripts/bench_api.sh .env.debug [CONC] [DUR] [THREADS]
# Defaults: CONC=50  DUR=10s  THREADS=2
#
# Needs: docker, jq, wrk, curl.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
ADMIN_PORT=23457
USER_PORT=23456

ENV_FILE="${1:-}"
if [[ -z "$ENV_FILE" ]]; then
  echo "usage: scripts/bench_api.sh <env_file> [CONC] [DUR] [THREADS]   (e.g. scripts/bench_api.sh .env.debug)" >&2
  exit 1
fi
[[ -f "$ENV_FILE" ]] || ENV_FILE="$ROOT/$ENV_FILE"
[[ -f "$ENV_FILE" ]] || { echo "env file not found: ${1}" >&2; exit 1; }
CONC="${2:-50}"
DUR="${3:-10s}"
THREADS="${4:-2}"

for bin in docker jq wrk curl; do
  command -v "$bin" >/dev/null || { echo "missing required command: $bin" >&2; exit 1; }
done

# --- project + container IPs (mirrors seed.py / loadtest.py) ----------------
PROJECT=$(grep -E '^[[:space:]]*COMPOSE_PROJECT_NAME[[:space:]]*=' "$ENV_FILE" \
  | tail -1 | cut -d= -f2- | tr -d ' "'"'")
[[ -n "$PROJECT" ]] || { echo "$ENV_FILE: COMPOSE_PROJECT_NAME not set" >&2; exit 1; }

resolve_ip() { # $1=service
  local cid ip
  cid=$(docker ps -q \
    --filter "label=com.docker.compose.project=$PROJECT" \
    --filter "label=com.docker.compose.service=$1" | head -1)
  [[ -n "$cid" ]] || {
    echo "no running $1 for project '$PROJECT'. Start it first:" >&2
    echo "  docker compose --env-file $ENV_FILE --profile storage --profile app up -d" >&2
    exit 1
  }
  ip=$(docker inspect -f '{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}' "$cid")
  [[ -n "$ip" ]] || { echo "$1 container ${cid:0:12} has no network IP" >&2; exit 1; }
  echo "$ip"
}

BASE="http://$(resolve_ip user-api):$USER_PORT"
ADMIN="http://$(resolve_ip admin-api):$ADMIN_PORT"

# --- throwaway account (random, self-contained) -----------------------------
USER="bench_$(openssl rand -hex 3 2>/dev/null || date +%s)"
PASS="$(openssl rand -base64 12 2>/dev/null | tr -dc 'A-Za-z0-9' | head -c 16)"
PASS="${PASS:-benchpass123}"

acct_body=$(curl -s -o /tmp/bench_acct.$$ -w '%{http_code}' -X POST "$ADMIN/api/admin/accounts" \
  -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USER\",\"password\":\"$PASS\",\"display_name\":\"$USER\"}")
if [[ "$acct_body" != 200 && "$acct_body" != 201 ]]; then
  echo "create account failed: HTTP $acct_body — $(cat /tmp/bench_acct.$$ 2>/dev/null)" >&2
  echo "(is a provider seeded? account creation 409s without one)" >&2
  rm -f /tmp/bench_acct.$$
  exit 1
fi
rm -f /tmp/bench_acct.$$

TOKEN=$(curl -s -X POST "$BASE/api/auth/login" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$USER\",\"password\":\"$PASS\"}" | jq -r '.token // empty')
[ -n "$TOKEN" ] || { echo "login failed against $BASE" >&2; exit 1; }
AUTH="Authorization: Bearer $TOKEN"

# --- endpoint discovery + benchmark -----------------------------------------
firstid() { curl -s -H "$AUTH" "$BASE$1" \
  | jq -r '(.[0].conversation.id // .[0].id // .[0].conversation_id // .[0].inbox_id // .[0].persona_id // .[0].job_id // empty)' 2>/dev/null; }

CONV=$(firstid /api/conversations)
INBOX=$(firstid /api/inboxes)
PERSONA=$(firstid /api/personas)
JOB=$(firstid /api/distill-jobs)
CHATCONV=$(firstid /api/chat/conversations)

EPS=(
  /api/auth/me
  /api/inboxes
  /api/conversations
  /api/bridges
  /api/personas
  /api/distill-jobs
  /api/chat/contacts
  /api/chat/conversations
)
[ -n "$INBOX" ]    && EPS+=("/api/inboxes/$INBOX")
[ -n "$CONV" ]     && EPS+=("/api/conversations/$CONV" "/api/conversations/$CONV/messages")
[ -n "$PERSONA" ]  && EPS+=("/api/personas/$PERSONA")
[ -n "$JOB" ]      && EPS+=("/api/distill-jobs/$JOB")
[ -n "$CHATCONV" ] && EPS+=("/api/chat/conversations/$CHATCONV/messages/before")

echo "PROJECT=$PROJECT  BASE=$BASE  CONC=$CONC  DUR=$DUR  THREADS=$THREADS  (acct $USER)"
echo "ids: conv=$CONV inbox=$INBOX persona=$PERSONA job=$JOB chatconv=$CHATCONV"
printf "%-52s %-5s %-9s %-9s %-9s %-5s\n" "ENDPOINT" "code" "RPS" "P50" "P99" "err"
for ep in "${EPS[@]}"; do
  code=$(curl -s -o /dev/null -w '%{http_code}' -H "$AUTH" "$BASE$ep")
  if [ "$code" != 200 ]; then
    printf "%-52s %-5s %s\n" "$ep" "$code" "SKIP"
    continue
  fi
  out=$(wrk -t"$THREADS" -c"$CONC" -d"$DUR" --latency -H "$AUTH" "$BASE$ep" 2>&1)
  rps=$(echo "$out" | awk '/Requests\/sec/{print $2}')
  p50=$(echo "$out" | awk '/^ *50%/{print $2}')
  p99=$(echo "$out" | awk '/^ *99%/{print $2}')
  err=$(echo "$out" | awk '/Non-2xx/{print $NF}'); err=${err:-0}
  printf "%-52s %-5s %-9s %-9s %-9s %-5s\n" "$ep" "$code" "$rps" "$p50" "$p99" "$err"
done
