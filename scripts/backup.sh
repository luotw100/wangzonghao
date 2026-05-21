#!/usr/bin/env bash
# Hot backup of one instance's stateful data: Studio PG + Chat PG +
# MinIO buckets. Safe to run while services are up (pg_dump is
# transaction-consistent; mc mirror is object-level).
#
# Takes the instance config (the same one as up-all.sh) so it targets
# that instance's containers (compose project = COMPOSE_PROJECT_NAME):
#
#   scripts/backup.sh scripts/.env.release.json
#   BACKUP_DIR=/mnt/backups scripts/backup.sh scripts/.env.release.json  # custom root
#   LABEL=before-seed-reset scripts/backup.sh scripts/.env.release.json  # tag why
#
# This script NEVER deletes a backup. Pruning old backups is entirely
# manual and up to you -- there is no retention/rotation logic.
#
# At the end it LOCKS the new backup with `chattr +i` (needs sudo;
# you'll be prompted for your password) so it cannot be deleted/changed.
# To delete a backup later you must first unlock it:
#   sudo chattr -R -i ~/laborster-backups/<the-one-you-chose>
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

# infra/.env carries the PG/MinIO creds (seam); the instance JSON's
# `compose` block carries COMPOSE_PROJECT_NAME so we target the right
# instance. Render that block to a tmp KV so docker compose can read it.
TMP_ENV=$(mktemp); trap "rm -f $TMP_ENV" EXIT
jq -r '.compose | to_entries[] | "\(.key)=\(.value)"' "$INST" > "$TMP_ENV"
set -a; . "$INFRA_DIR/.env"; . "$TMP_ENV"; set +a
: "${COMPOSE_PROJECT_NAME:?config.compose must set COMPOSE_PROJECT_NAME}"

COMPOSE=(docker compose -f "$INFRA_DIR/compose.yaml" --project-directory "$INFRA_DIR" \
  -p "$COMPOSE_PROJECT_NAME" --env-file "$INFRA_DIR/.env")
BACKUP_DIR="${BACKUP_DIR:-$HOME/laborster-backups}"
# Run helper containers as the host user so output files are owned by
# you, not root (no more mixed ownership in the backup dir).
HOST_UGID="$(id -u):$(id -g)"

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
NAME="${STAMP}__${COMPOSE_PROJECT_NAME}__${SAFE_BRANCH}_${SHORT_HASH}${DIRTY}"
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

# Browse-friendly copy: a single .sqlite file you can open in the VSCode
# SQLite extension / DB Browser / any SQLite tool and view like a
# spreadsheet. The .dump stays the canonical/restorable artifact; this
# is purely for eyeballing data. Uses only already-cached, maintained
# official images (postgres + python stdlib sqlite3) -- no third-party
# tool, works offline. Columns land as TEXT (SQLite is dynamically
# typed; values display fine). Best-effort: never fails the backup.
sqlite_pg() {
  local svc="$1" user="$2" db="$3" out="$4"
  echo ">>> Building $out (sqlite, browse copy)"
  rm -f "$DEST/$out"
  local tmp="$DEST/.csv-${out%.sqlite}"
  mkdir -p "$tmp"
  # Read table list into an array (a `while read` loop would have its
  # stdin eaten by `docker compose exec`, truncating the iteration).
  local tables=()
  mapfile -t tables < <("${COMPOSE[@]}" exec -T "$svc" \
    psql -U "$user" -d "$db" -tAc \
    "SELECT tablename FROM pg_tables WHERE schemaname='public' ORDER BY 1" \
    </dev/null 2>/dev/null || true)
  [ "${#tables[@]}" -gt 0 ] || { echo "    WARN: no tables read; skipping $out"; rm -rf "$tmp"; return; }
  local t
  for t in "${tables[@]}"; do
    [ -n "$t" ] || continue
    "${COMPOSE[@]}" exec -T "$svc" psql -U "$user" -d "$db" \
      -c "\copy (SELECT * FROM public.\"$t\") TO STDOUT WITH CSV HEADER" \
      </dev/null > "$tmp/$t.csv" 2>/dev/null || true
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

dump_pg studio-db "$STUDIO_POSTGRES_USER" "$STUDIO_POSTGRES_DB" studio.dump
dump_pg chat-db   "$CHAT_POSTGRES_USER"   "$CHAT_POSTGRES_DB"   chat.dump

sqlite_pg studio-db "$STUDIO_POSTGRES_USER" "$STUDIO_POSTGRES_DB" studio.sqlite
sqlite_pg chat-db   "$CHAT_POSTGRES_USER"   "$CHAT_POSTGRES_DB"   chat.sqlite

echo ">>> Mirroring MinIO buckets"
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
    mc mirror --overwrite --remove local/studio /backup/studio;
    mc mirror --overwrite --remove local/chat   /backup/chat;
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

# Self-documenting: read instructions travel with the data, no repo needed.
cat > "$DEST/HOW_TO_READ.txt" <<'EOF'
HOW TO READ THIS BACKUP
=======================

NOT ENCRYPTED. *.dump are plaintext-equivalent full data copies
(pg_dump custom format). Treat this directory as sensitive: never
put it in git, public cloud, or share it casually.

EASIEST: just open studio.sqlite / chat.sqlite to browse data like a
spreadsheet -- VSCode "SQLite" / "SQLite Viewer" extension, DB Browser
for SQLite, or any SQLite tool. No password, no Docker, no commands.
The .sqlite is a convenience copy; *.dump below is the authoritative
restorable backup.

The commands below are only for the *.dump files.
You do NOT need a password. You only need Docker (or local pg tools).
Run these from inside this directory.

1) List tables/objects in a dump (no data extracted):
   docker run --rm -v "$PWD":/b postgres:16-alpine \
     pg_restore --list /b/studio.dump

2) Convert a dump to readable SQL text (note: -f - is required):
   docker run --rm -v "$PWD":/b postgres:16-alpine \
     pg_restore --no-owner --no-privileges -f - /b/studio.dump > studio.sql

3) Dump one table's data only (note: -f - is required):
   docker run --rm -v "$PWD":/b postgres:16-alpine \
     pg_restore --data-only --table=personas -f - /b/studio.dump

4) Restore into a live database:
   docker run --rm -v "$PWD":/b -e PGPASSWORD=<pw> postgres:16-alpine \
     pg_restore --no-owner --clean --if-exists \
     -h <host> -U <user> -d <db> /b/studio.dump

5) MinIO objects: ./minio/studio and ./minio/chat hold raw object
   files (empty if the bucket had no objects). Open directly, no tools.

See MANIFEST.txt for the exact commit, branch and schema version this
data corresponds to before restoring.
EOF

# No retention/rotation: this script never deletes a backup. Deleting
# old backups is a manual decision. Just report disk usage as an FYI.
echo ">>> Backups kept: $(ls -1d "$BACKUP_DIR"/20*/ 2>/dev/null | wc -l), total on disk:"
du -sh "$BACKUP_DIR" 2>/dev/null | sed 's/^/    /'

echo ">>> Backup complete: $DEST"

# Make this backup immutable (chattr +i) so it cannot be deleted or
# overwritten -- not even by you with `rm -rf` -- until you explicitly
# `sudo chattr -R -i` it. Needs sudo; you will be asked for your
# password below. Best-effort: the backup is already safely written,
# locking failure does not lose data.
echo
echo "=================================================================="
echo "  LOCKING BACKUP (chattr +i) -- making it delete-proof"
echo "  >>> sudo may ask for your password now. Type it to lock. <<<"
echo "=================================================================="
if sudo chattr -R +i "$DEST"; then
  echo "=================================================================="
  echo "  OK -- backup LOCKED: $DEST"
  echo "  To delete it later you must first unlock:"
  echo "    sudo chattr -R -i \"$DEST\""
  echo "=================================================================="
else
  echo "=================================================================="
  echo "  WARN: lock FAILED (sudo declined / chattr unsupported)."
  echo "  Backup data is fine and complete, just NOT delete-protected."
  echo "  Lock it manually with: sudo chattr -R +i \"$DEST\""
  echo "=================================================================="
fi
