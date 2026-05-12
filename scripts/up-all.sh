#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

echo ">>> Starting infra"
docker compose -f "$PROJECT_ROOT/infra/compose.yaml" --project-directory "$PROJECT_ROOT/infra" up -d

echo ">>> Waiting for databases to be ready"
sleep 3

for compose_file in "$PROJECT_ROOT"/services/chat/compose.yaml "$PROJECT_ROOT"/services/studio/compose.yaml; do
  compose_dir="$(dirname "$compose_file")"
  service_name="$(basename "$compose_dir")"
  echo ">>> Starting $service_name"
  docker compose -f "$compose_file" --project-directory "$compose_dir" up --build -d
done

echo ">>> All services started"