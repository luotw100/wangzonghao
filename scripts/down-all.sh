#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"

for compose_file in "$PROJECT_ROOT"/services/chat/compose.yaml "$PROJECT_ROOT"/services/studio/compose.yaml "$PROJECT_ROOT"/infra/compose.yaml; do
  compose_dir="$(dirname "$compose_file")"
  service_name="$(basename "$compose_dir")"
  echo ">>> Stopping $service_name"
  docker compose -f "$compose_file" --project-directory "$compose_dir" down
done

echo ">>> All services stopped"