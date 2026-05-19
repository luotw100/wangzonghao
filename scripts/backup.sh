#!/usr/bin/env bash
# Hot backup of all stateful data: Studio PG + Chat PG + MinIO buckets.
# Safe to run while services are up (pg_dump is transaction-consistent;
# mc mirror is object-level). pgadmin-data is intentionally NOT backed up.
#
#   scripts/backup.sh                          # -> ~/laborster-backups/<name>/
#   BACKUP_DIR=/mnt/backups scripts/backup.sh  # custom root, outside the repo
#   LABEL=before-seed-reset scripts/backup.sh  # tag why this snapshot exists
#   KEEP=20 scripts/backup.sh                  # keep last 20 (default 10)
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INFRA_DIR="$REPO_DIR/infra"
COMPOSE=(docker compose -f "$INFRA_DIR/compose.yaml" --project-directory "$INFRA_DIR")
KEEP="${KEEP:-10}"
BACKUP_DIR="${BACKUP_DIR:-$HOME/laborster-backups}"

[ -f "$INFRA_DIR/.env" ] || { echo "ERROR: $INFRA_DIR/.env not found" >&2; exit 1; }
set -a; . "$INFRA_DIR/.env"; set +a

# --- Provenance: tie this snapshot to an exact code state -------------------
git_in_repo() { git -C "$REPO_DIR" "$@" 2>/dev/null; }
BRANCH="$(git_in_repo rev-parse --abbrev-ref HEAD || echo nogit)"
SHORT_HASH="$(git_in_repo rev-parse --short HEAD || echo nogit)"
FULL_HASH="$(git_in_repo rev-parse HEAD || echo nogit)"
COMMIT_SUBJECT="$(git_in_repo log -1 --pretty=%s || echo -)"
DIRTY=""
[ -n "$(git_in_repo status --porcelain || true)" ] && DIRTY="-dirty"
SAFE_BRANCH="${BRANCH//\//-}"

STAMP="$(date +%Y-%m-%d_%H%M%S)"
NAME="${STAMP}__${SAFE_BRANCH}_${SHORT_HASH}${DIRTY}"
[ -n "${LABEL:-}" ] && NAME="${NAME}__${LABEL}"
DEST="$BACKUP_DIR/$NAME"
mkdir -p "$DEST/minio"

echo ">>> Backup target: $DEST"

dump_pg() {
  local svc="$1" user="$2" db="$3" out="$4"
  echo ">>> Dumping $svc ($db)"
  "${COMPOSE[@]}" exec -T "$svc" pg_dump -U "$user" -d "$db" -Fc > "$DEST/$out"
}

# Best-effort schema version (Alembic). Never fails the backup.
schema_ver() {
  local svc="$1" user="$2" db="$3"
  "${COMPOSE[@]}" exec -T "$svc" \
    psql -U "$user" -d "$db" -tAc \
    'SELECT version_num FROM alembic_version' 2>/dev/null | tr -d '[:space:]' || true
}

dump_pg studio-db "$STUDIO_POSTGRES_USER" "$STUDIO_POSTGRES_DB" studio.dump
dump_pg chat-db   "$CHAT_POSTGRES_USER"   "$CHAT_POSTGRES_DB"   chat.dump

echo ">>> Mirroring MinIO buckets"
MINIO_CID="$("${COMPOSE[@]}" ps -q minio)"
[ -n "$MINIO_CID" ] || { echo "ERROR: minio container not running" >&2; exit 1; }
docker run --rm \
  --network "container:$MINIO_CID" \
  -v "$DEST/minio:/backup" \
  --entrypoint /bin/sh \
  minio/mc:RELEASE.2025-08-13T08-35-41Z -c "
    mc alias set local http://localhost:9000 '$MINIO_ROOT_USER' '$MINIO_ROOT_PASSWORD' >/dev/null;
    mc mirror --overwrite --remove local/studio /backup/studio;
    mc mirror --overwrite --remove local/chat   /backup/chat;
  "

{
  echo "created     : $STAMP"
  echo "label       : ${LABEL:-(none)}"
  echo "branch      : $BRANCH"
  echo "commit      : $FULL_HASH${DIRTY}"
  echo "subject     : $COMMIT_SUBJECT"
  echo "host / user : $(hostname) / ${USER:-$(id -un)}"
  echo "pg image    : postgres:16-alpine"
  echo "mc image    : minio/mc:RELEASE.2025-08-13T08-35-41Z"
  echo "studio schema: $(schema_ver studio-db "$STUDIO_POSTGRES_USER" "$STUDIO_POSTGRES_DB")"
  echo "chat schema  : $(schema_ver chat-db "$CHAT_POSTGRES_USER" "$CHAT_POSTGRES_DB")"
  if [ -n "$DIRTY" ]; then
    echo "dirty files :"
    git_in_repo status --porcelain | sed 's/^/  /'
  fi
  echo "files       :"
  ( cd "$DEST" && du -ah --max-depth=1 | sort -k2 )
} > "$DEST/MANIFEST.txt"
cat "$DEST/MANIFEST.txt"

# Rolling retention: keep newest $KEEP, drop the rest.
cd "$BACKUP_DIR"
ls -1d 20*/ 2>/dev/null | sort -r | tail -n +"$((KEEP + 1))" | while read -r old; do
  echo ">>> Pruning old backup: $old"
  rm -rf -- "$old"
done

echo ">>> Backup complete: $DEST"
