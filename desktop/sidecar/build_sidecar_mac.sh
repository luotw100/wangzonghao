#!/usr/bin/env bash
# Freeze the sidecar into a single binary: desktop/sidecar/dist/laborster-sidecar.
# electron-builder then bundles it as an extra resource. Ad-hoc codesign
# is required on Apple Silicon; the surrounding .app gets re-signed by
# electron-builder, but signing the inner binary first avoids a kill on
# first spawn.
#
# Requires `uv` on PATH (the only build-time prereq; not shipped to users).
set -euo pipefail
cd "$(dirname "$0")"

# Runtime deps + the PyInstaller toolchain both come from pyproject + uv.lock,
# the single source of truth. --frozen builds from the pinned lock and fails
# if it's stale, so the released binary is reproducible.
uv sync --frozen --group build
uv run --no-sync pyinstaller --noconfirm --clean --onefile \
  --name laborster-sidecar \
  --collect-submodules laborster_bridge \
  --collect-all certifi \
  server.py

codesign --force --sign - dist/laborster-sidecar || true
echo "built: $(pwd)/dist/laborster-sidecar"
