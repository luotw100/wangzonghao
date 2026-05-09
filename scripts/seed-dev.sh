#!/usr/bin/env bash
# scripts/seed-dev.sh — One-shot dev seed.
#
# Run this after `docker compose up -d --build` in services/chat and
# services/studio. Creates:
#   - one Chat user (via chat CLI)
#   - one Studio admin + one Studio normal user (via studio CLI)
#   - one Studio Provider (via Studio API, admin auth)
#   - one Persona under the Studio user (via Studio API, user auth)
#   - one Chat contact + a few seeded messages (via Chat API, user auth)
#
# Re-run after wiping volumes (docker compose down -v) to get back to a
# known-good baseline. Existing accounts are skipped, not updated.

set -u
set -o pipefail

# ---------- config ----------

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
CHAT_DIR="$REPO_ROOT/services/chat"
STUDIO_DIR="$REPO_ROOT/services/studio"

CHAT_URL="${CHAT_URL:-http://localhost:23456}"
STUDIO_URL="${STUDIO_URL:-http://localhost:23457}"

CHAT_USERNAME="${CHAT_USERNAME:-alice}"
CHAT_PASSWORD="${CHAT_PASSWORD:-Alice123}"
CHAT_DISPLAY_NAME="${CHAT_DISPLAY_NAME:-主播 alice}"

STUDIO_ADMIN_USERNAME="${STUDIO_ADMIN_USERNAME:-admin}"
STUDIO_ADMIN_PASSWORD="${STUDIO_ADMIN_PASSWORD:-Admin123}"
STUDIO_ADMIN_DISPLAY_NAME="${STUDIO_ADMIN_DISPLAY_NAME:-平台管理员}"

STUDIO_USER_USERNAME="${STUDIO_USER_USERNAME:-demo}"
STUDIO_USER_PASSWORD="${STUDIO_USER_PASSWORD:-Demo123}"
STUDIO_USER_DISPLAY_NAME="${STUDIO_USER_DISPLAY_NAME:-主播 demo}"

# Provider — hard-coded for dev. Move to env if it ever gets sensitive.
PROVIDER_NAME="dev-deepseek"
PROVIDER_BASE_URL="https://api.deepseek.com"
PROVIDER_API_KEY="sk-3898e65a9f9b486b8ecf0eff724d32e2"
PROVIDER_MODEL="deepseek-v4-flash"

PERSONA_NAME="${PERSONA_NAME:-demo人设}"
PERSONA_MD="${PERSONA_MD:-我是主播 demo，喜欢户外、冷感美学、不爱寒暄。回复偏短、自然、有点点温度。}"

CHAT_CONTACT_NAME="${CHAT_CONTACT_NAME:-小红}"

# ---------- helpers ----------

log()  { printf '\033[36m[seed]\033[0m %s\n' "$*"; }
ok()   { printf '\033[32m[ok]\033[0m   %s\n' "$*"; }
warn() { printf '\033[33m[warn]\033[0m %s\n' "$*"; }
die()  { printf '\033[31m[fail]\033[0m %s\n' "$*" >&2; exit 1; }

require_cmd() { command -v "$1" >/dev/null 2>&1 || die "missing required command: $1"; }

require_cmd docker
require_cmd curl
require_cmd python3

json_escape() {
  # Read stdin, emit a JSON-quoted string (handles \, ", \n, ...).
  python3 -c 'import json,sys; sys.stdout.write(json.dumps(sys.stdin.read()))'
}

json_get() {
  # json_get '<json>' '<key>'  -> stdout = value (or empty on miss)
  python3 -c '
import json, sys
data = json.loads(sys.argv[1] or "null")
key = sys.argv[2]
if isinstance(data, dict) and key in data:
    v = data[key]
    print(v if isinstance(v, str) else json.dumps(v))
' "$1" "$2"
}

http_post() {
  # http_post URL TOKEN_OR_EMPTY JSON_BODY -> echoes "<status> <body>"
  local url="$1" token="$2" body="$3"
  local args=(-sS -o /tmp/seed_resp -w '%{http_code}' -X POST -H 'Content-Type: application/json')
  [ -n "$token" ] && args+=(-H "Authorization: Bearer $token")
  args+=(--data-binary "$body" "$url")
  local code
  code=$(curl "${args[@]}") || code="000"
  printf '%s ' "$code"
  cat /tmp/seed_resp
  printf '\n'
}

http_get() {
  local url="$1" token="$2"
  local args=(-sS -o /tmp/seed_resp -w '%{http_code}' -X GET)
  [ -n "$token" ] && args+=(-H "Authorization: Bearer $token")
  args+=("$url")
  local code
  code=$(curl "${args[@]}") || code="000"
  printf '%s ' "$code"
  cat /tmp/seed_resp
  printf '\n'
}

wait_health() {
  local url="$1" name="$2" tries=30
  while [ "$tries" -gt 0 ]; do
    if curl -sSf -o /dev/null "$url/api/health"; then
      ok "$name healthy"
      return 0
    fi
    tries=$((tries - 1))
    sleep 1
  done
  die "$name not reachable at $url — start the stack first"
}

# ---------- step 1: CLI account creation ----------

create_chat_account() {
  log "creating chat account: $CHAT_USERNAME"
  ( cd "$CHAT_DIR" && \
    docker compose exec -T chat-api uv run python -m chat.cli create-account \
      --username "$CHAT_USERNAME" \
      --password "$CHAT_PASSWORD" \
      --display-name "$CHAT_DISPLAY_NAME" \
  ) && ok "chat account ready" \
    || warn "chat-cli returned non-zero (likely 'account already exists') — continuing"
}

create_studio_account() {
  local user="$1" pass="$2" display="$3" role="$4"
  log "creating studio account: $user ($role)"
  ( cd "$STUDIO_DIR" && \
    docker compose exec -T studio-api uv run python -m studio.cli create-account \
      --username "$user" \
      --password "$pass" \
      --display-name "$display" \
      --role "$role" \
  ) && ok "studio account ready: $user" \
    || warn "studio-cli returned non-zero for $user (likely 'account already exists') — continuing"
}

# ---------- step 2: Studio API seeding ----------

studio_login() {
  local user="$1" pass="$2"
  local body
  body=$(printf '{"username":%s,"password":%s}' \
    "$(printf '%s' "$user" | json_escape)" \
    "$(printf '%s' "$pass" | json_escape)")
  local out code rest
  out=$(http_post "$STUDIO_URL/api/auth/login" "" "$body")
  code="${out%% *}"; rest="${out#* }"
  [ "$code" = "200" ] || { warn "studio login failed for $user (HTTP $code): $rest"; echo ""; return; }
  json_get "$rest" token
}

studio_seed_provider() {
  local admin_token="$1"

  # Skip if any provider already exists.
  local out code rest
  out=$(http_get "$STUDIO_URL/api/provider-configs" "$admin_token")
  code="${out%% *}"; rest="${out#* }"
  if [ "$code" = "200" ] && [ "$(printf '%s' "$rest" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))')" -gt 0 ]; then
    ok "studio provider already configured — skipping"
    return
  fi

  log "creating studio provider: $PROVIDER_NAME"
  local body
  body=$(printf '{"name":%s,"base_url":%s,"api_key":%s,"default_model":%s}' \
    "$(printf '%s' "$PROVIDER_NAME"     | json_escape)" \
    "$(printf '%s' "$PROVIDER_BASE_URL" | json_escape)" \
    "$(printf '%s' "$PROVIDER_API_KEY"  | json_escape)" \
    "$(printf '%s' "$PROVIDER_MODEL"    | json_escape)")
  out=$(http_post "$STUDIO_URL/api/provider-configs" "$admin_token" "$body")
  code="${out%% *}"; rest="${out#* }"
  [ "$code" = "200" ] || { warn "create provider failed (HTTP $code): $rest"; return; }
  ok "studio provider created"
}

studio_seed_persona() {
  local user_token="$1"

  # Skip if user already has any persona.
  local out code rest
  out=$(http_get "$STUDIO_URL/api/personas" "$user_token")
  code="${out%% *}"; rest="${out#* }"
  if [ "$code" = "200" ] && [ "$(printf '%s' "$rest" | python3 -c 'import json,sys;print(len(json.load(sys.stdin)))')" -gt 0 ]; then
    ok "studio persona already exists for $STUDIO_USER_USERNAME — skipping"
    return
  fi

  log "creating persona '$PERSONA_NAME' for $STUDIO_USER_USERNAME"
  local body
  body=$(printf '{"name":%s,"persona_md":%s}' \
    "$(printf '%s' "$PERSONA_NAME" | json_escape)" \
    "$(printf '%s' "$PERSONA_MD"   | json_escape)")
  out=$(http_post "$STUDIO_URL/api/personas" "$user_token" "$body")
  code="${out%% *}"; rest="${out#* }"
  [ "$code" = "200" ] || { warn "create persona failed (HTTP $code): $rest"; return; }
  ok "studio persona created"
}

# ---------- step 3: Chat API seeding ----------

chat_login() {
  local body
  body=$(printf '{"username":%s,"password":%s}' \
    "$(printf '%s' "$CHAT_USERNAME" | json_escape)" \
    "$(printf '%s' "$CHAT_PASSWORD" | json_escape)")
  local out code rest
  out=$(http_post "$CHAT_URL/api/auth/login" "" "$body")
  code="${out%% *}"; rest="${out#* }"
  [ "$code" = "200" ] || { warn "chat login failed (HTTP $code): $rest"; echo ""; return; }
  json_get "$rest" token
}

chat_seed_messages() {
  local token="$1"

  # Reuse an existing contact if there is one.
  local out code rest contact_id=""
  out=$(http_get "$CHAT_URL/api/contacts" "$token")
  code="${out%% *}"; rest="${out#* }"
  if [ "$code" = "200" ]; then
    contact_id=$(printf '%s' "$rest" | python3 -c '
import json, sys
arr = json.load(sys.stdin)
print(arr[0]["id"] if arr else "")
')
  fi

  if [ -z "$contact_id" ]; then
    log "creating chat contact: $CHAT_CONTACT_NAME"
    local body
    body=$(printf '{"display_name":%s}' "$(printf '%s' "$CHAT_CONTACT_NAME" | json_escape)")
    out=$(http_post "$CHAT_URL/api/contacts" "$token" "$body")
    code="${out%% *}"; rest="${out#* }"
    [ "$code" = "200" ] || { warn "create contact failed (HTTP $code): $rest"; return; }
    contact_id=$(json_get "$rest" id)
    [ -n "$contact_id" ] || { warn "no contact id in response: $rest"; return; }
  else
    ok "chat contact already exists ($contact_id) — reusing"
  fi

  # Ensure a conversation exists for the contact.
  local body
  body=$(printf '{"contact_id":%s}' "$(printf '%s' "$contact_id" | json_escape)")
  out=$(http_post "$CHAT_URL/api/conversations" "$token" "$body")
  code="${out%% *}"; rest="${out#* }"
  [ "$code" = "200" ] || { warn "create conversation failed (HTTP $code): $rest"; return; }
  local conversation_id
  conversation_id=$(json_get "$rest" id)
  [ -n "$conversation_id" ] || { warn "no conversation id in response: $rest"; return; }

  log "posting seed messages to conversation $conversation_id"
  local seed_jsonl='[
    {"sender_type":"contact","msg_type":"text","content":"在吗？想咨询一下你上次推荐的茶。"},
    {"sender_type":"self","msg_type":"text","content":"在的，你说。"},
    {"sender_type":"contact","msg_type":"text","content":"我是上海的，那款白茶现在还有吗？"},
    {"sender_type":"self","msg_type":"text","content":"有，明早发顺丰。"}
  ]'
  printf '%s' "$seed_jsonl" | python3 -c '
import json, sys
for item in json.load(sys.stdin):
    print(json.dumps(item))
' | while IFS= read -r msg; do
    out=$(http_post "$CHAT_URL/api/conversations/$conversation_id/messages" "$token" "$msg")
    code="${out%% *}"; rest="${out#* }"
    [ "$code" = "200" ] || warn "send message failed (HTTP $code): $rest"
  done
  ok "seeded chat messages"
}

# ---------- main ----------

main() {
  log "studio: $STUDIO_URL  chat: $CHAT_URL"
  wait_health "$CHAT_URL"   "chat-api"
  wait_health "$STUDIO_URL" "studio-api"

  create_chat_account
  create_studio_account "$STUDIO_ADMIN_USERNAME" "$STUDIO_ADMIN_PASSWORD" "$STUDIO_ADMIN_DISPLAY_NAME" admin
  create_studio_account "$STUDIO_USER_USERNAME"  "$STUDIO_USER_PASSWORD"  "$STUDIO_USER_DISPLAY_NAME"  user

  local admin_token
  admin_token=$(studio_login "$STUDIO_ADMIN_USERNAME" "$STUDIO_ADMIN_PASSWORD")
  if [ -n "$admin_token" ]; then
    studio_seed_provider "$admin_token"
  else
    warn "skipping provider seed — admin login failed"
  fi

  local user_token
  user_token=$(studio_login "$STUDIO_USER_USERNAME" "$STUDIO_USER_PASSWORD")
  if [ -n "$user_token" ]; then
    studio_seed_persona "$user_token"
  else
    warn "skipping persona seed — user login failed"
  fi

  local chat_token
  chat_token=$(chat_login)
  if [ -n "$chat_token" ]; then
    chat_seed_messages "$chat_token"
  else
    warn "skipping chat message seed — chat login failed"
  fi

  cat <<EOF

---
seed done. credentials:
  studio admin: $STUDIO_ADMIN_USERNAME / $STUDIO_ADMIN_PASSWORD   ($STUDIO_URL)
  studio user : $STUDIO_USER_USERNAME / $STUDIO_USER_PASSWORD   ($STUDIO_URL)
  chat user   : $CHAT_USERNAME / $CHAT_PASSWORD   ($CHAT_URL)

next: start bridge with the snippet shown on Studio → 设备 → 快速生成命令.
EOF
}

main "$@"
