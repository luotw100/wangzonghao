#!/usr/bin/env bash
# Hot backup of one instance's stateful data: PG + MinIO bucket. Safe to
# run while services are up (pg_dump is transaction-consistent; mc mirror
# is object-level).
#
#   scripts/backup.sh scripts/.env.release.json
#   BACKUP_DIR=/mnt/backups scripts/backup.sh scripts/.env.release.json
#   LABEL=before-seed-reset scripts/backup.sh scripts/.env.release.json
#
# This script NEVER deletes a backup. Pruning is manual. At the end it
# LOCKS the new backup with `chattr +i` (needs sudo) so it can't be
# deleted/changed by mistake. To unlock later:
#   sudo chattr -R -i ~/laborster-backups/<the-one>
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
INFRA_DIR="$REPO_DIR/infra"

INST="${1:-}"
if [ -z "$INST" ]; then
  echo "usage: scripts/backup.sh <config.json>   (e.g. scripts/.env.release.json)" >&2
  exit 1
fi
case "$INST" in /*) :;; *) INST="$REPO_DIR/$INST";; esac
[ -f "$INST" ] || { echo "ERROR: config not found: $INST" >&2; exit 1; }
[ -f "$INFRA_DIR/.env" ] || { echo "ERROR: $INFRA_DIR/.env not found" >&2; exit 1; }
jq empty "$INST" 2>/dev/null || { echo "ERROR: invalid JSON: $INST" >&2; exit 1; }

TMP_ENV=$(mktemp); trap "rm -f $TMP_ENV" EXIT
jq -r '.compose | to_entries[] | "\(.key)=\(.value)"' "$INST" > "$TMP_ENV"
set -a; . "$INFRA_DIR/.env"; . "$TMP_ENV"; set +a
: "${COMPOSE_PROJECT_NAME:?config.compose must set COMPOSE_PROJECT_NAME}"

COMPOSE=(docker compose -f "$INFRA_DIR/compose.yaml" --project-directory "$INFRA_DIR" \
  -p "$COMPOSE_PROJECT_NAME" --env-file "$INFRA_DIR/.env")
BACKUP_DIR="${BACKUP_DIR:-$HOME/laborster-backups}"
HOST_UGID="$(id -u):$(id -g)"

# --- Provenance ----------------------------------------------------------
git_in_repo() { git -C "$REPO_DIR" "$@" 2>/dev/null; }
BRANCH="$(git_in_repo rev-parse --abbrev-ref HEAD || echo nogit)"
SHORT_HASH="$(git_in_repo rev-parse --short HEAD || echo nogit)"
FULL_HASH="$(git_in_repo rev-parse HEAD || echo nogit)"
COMMIT_SUBJECT="$(git_in_repo log -1 --pretty=%s || echo -)"
DIRTY=""
[ -n "$(git_in_repo status --porcelain || true)" ] && DIRTY="-dirty"
SAFE_BRANCH="${BRANCH//\//-}"

STAMP="$(date +%Y-%m-%d_%H%M%S)"
NAME="${STAMP}__${COMPOSE_PROJECT_NAME}__${SAFE_BRANCH}_${SHORT_HASH}${DIRTY}"
[ -n "${LABEL:-}" ] && NAME="${NAME}__${LABEL}"
DEST="$BACKUP_DIR/$NAME"
mkdir -p "$DEST/minio"

echo ">>> Backup target: $DEST"

dump_pg() {
  local out="$1"
  echo ">>> Dumping $POSTGRES_DB"
  "${COMPOSE[@]}" exec -T db pg_dump -U "$POSTGRES_USER" -d "$POSTGRES_DB" -Fc > "$DEST/$out"
}

schema_ver() {
  "${COMPOSE[@]}" exec -T db \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAc \
    'SELECT version_num FROM studio.alembic_version' 2>/dev/null | tr -d '[:space:]' || true
}

# Browse-friendly copy: a single .sqlite of every table across all schemas.
sqlite_pg() {
  local out="$1"
  echo ">>> Building $out (sqlite, browse copy)"
  rm -f "$DEST/$out"
  local tmp="$DEST/.csv-${out%.sqlite}"
  mkdir -p "$tmp"
  local rows=()
  mapfile -t rows < <("${COMPOSE[@]}" exec -T db \
    psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" -tAF '|' -c \
    "SELECT schemaname, tablename FROM pg_tables WHERE schemaname IN ('auth','studio','chat') ORDER BY 1,2" \
    </dev/null 2>/dev/null || true)
  [ "${#rows[@]}" -gt 0 ] || { echo "    WARN: no tables read; skipping $out"; rm -rf "$tmp"; return; }
  local entry sch tbl
  for entry in "${rows[@]}"; do
    [ -n "$entry" ] || continue
    sch="${entry%%|*}"; tbl="${entry##*|}"
    "${COMPOSE[@]}" exec -T db psql -U "$POSTGRES_USER" -d "$POSTGRES_DB" \
      -c "\copy (SELECT * FROM ${sch}.\"$tbl\") TO STDOUT WITH CSV HEADER" \
      </dev/null > "$tmp/${sch}__${tbl}.csv" 2>/dev/null || true
  done

  docker run --rm -i --user "$HOST_UGID" -v "$tmp:/csv" -v "$DEST:/out" python:3.12-slim \
    python - "/out/$out" <<'PY' || echo "    WARN: sqlite build had issues; .dump is the authoritative copy"
import csv, glob, os, sqlite3, sys
db = sqlite3.connect(sys.argv[1])
for path in sorted(glob.glob("/csv/*.csv")):
    name = os.path.splitext(os.path.basename(path))[0]
    with open(path, newline="") as fh:
        r = csv.reader(fh)
        try:
            header = next(r)
        except StopIteration:
            continue
        q = lambda s: '"' + s.replace('"', '""') + '"'
        cols = ", ".join(q(c) for c in header)
        db.execute(f'CREATE TABLE {q(name)} ({", ".join(q(c)+" TEXT" for c in header)})')
        ph = ", ".join("?" * len(header))
        db.executemany(f'INSERT INTO {q(name)} ({cols}) VALUES ({ph})',
                       (row for row in r if len(row) == len(header)))
db.commit()
db.close()
PY
  rm -rf "$tmp"
}

dump_pg laborster.dump
sqlite_pg laborster.sqlite

echo ">>> Mirroring MinIO bucket"
MINIO_CID="$("${COMPOSE[@]}" ps -q minio)"
[ -n "$MINIO_CID" ] || { echo "ERROR: minio container not running" >&2; exit 1; }
docker run --rm \
  --network "container:$MINIO_CID" \
  --user "$HOST_UGID" \
  -e MC_CONFIG_DIR=/tmp/mc \
  -v "$DEST/minio:/backup" \
  --entrypoint /bin/sh \
  minio/mc:RELEASE.2025-08-13T08-35-41Z -c "
    mc alias set local http://localhost:9000 '$MINIO_ROOT_USER' '$MINIO_ROOT_PASSWORD' >/dev/null;
    mc mirror --overwrite --remove local/$S3_BUCKET /backup/$S3_BUCKET;
  "

{
  echo "created     : $STAMP"
  echo "instance    : $COMPOSE_PROJECT_NAME"
  echo "label       : ${LABEL:-(none)}"
  echo "branch      : $BRANCH"
  echo "commit      : $FULL_HASH${DIRTY}"
  echo "subject     : $COMMIT_SUBJECT"
  echo "host / user : $(hostname) / ${USER:-$(id -un)}"
  echo "pg image    : postgres:16-alpine"
  echo "mc image    : minio/mc:RELEASE.2025-08-13T08-35-41Z"
  echo "schema_ver  : $(schema_ver)"
  if [ -n "$DIRTY" ]; then
    echo "dirty files :"
    git_in_repo status --porcelain | sed 's/^/  /'
  fi
  echo "files       :"
  ( cd "$DEST" && du -ah --max-depth=1 | sort -k2 )
} > "$DEST/MANIFEST.txt"
cat "$DEST/MANIFEST.txt"

cat > "$DEST/HOW_TO_READ.txt" <<'EOF'
HOW TO READ THIS BACKUP
=======================

NOT ENCRYPTED. *.dump is a plaintext-equivalent full data copy
(pg_dump custom format). Treat this dir as sensitive.

EASIEST: open laborster.sqlite to browse data like a spreadsheet
(VSCode "SQLite Viewer", DB Browser for SQLite, ...). All schemas
(auth / studio / chat) flatten into prefixed tables like
"auth__accounts", "chat__messages", etc.

The .sqlite is a convenience copy; laborster.dump below is the
authoritative restorable backup.

1) List objects in the dump:
   docker run --rm -v "$PWD":/b postgres:16-alpine \
     pg_restore --list /b/laborster.dump

2) Convert dump to readable SQL:
   docker run --rm -v "$PWD":/b postgres:16-alpine \
     pg_restore --no-owner --no-privileges -f - /b/laborster.dump > laborster.sql

3) Restore into a live database:
   docker run --rm -v "$PWD":/b -e PGPASSWORD=<pw> postgres:16-alpine \
     pg_restore --no-owner --clean --if-exists \
     -h <host> -U <user> -d <db> /b/laborster.dump

4) MinIO objects live under ./minio/<bucket>/.

See MANIFEST.txt for the exact commit and schema version.
EOF

echo ">>> Backups kept: $(ls -1d "$BACKUP_DIR"/20*/ 2>/dev/null | wc -l), total on disk:"
du -sh "$BACKUP_DIR" 2>/dev/null | sed 's/^/    /'

echo ">>> Backup complete: $DEST"

echo
echo "=================================================================="
echo "  LOCKING BACKUP (chattr +i) -- making it delete-proof"
echo "  >>> sudo may ask for your password now. Type it to lock. <<<"
echo "=================================================================="
if sudo chattr -R +i "$DEST"; then
  echo "  OK -- LOCKED: $DEST"
  echo "  To delete later: sudo chattr -R -i \"$DEST\""
else
  echo "  WARN: lock FAILED. Backup data is fine, just not delete-protected."
fi
