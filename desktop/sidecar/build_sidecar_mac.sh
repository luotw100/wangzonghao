#!/usr/bin/env bash
# Freeze the sidecar into a single binary: desktop/sidecar/dist/laborster-sidecar.
# electron-builder then bundles it as an extra resource. Ad-hoc codesign
# is required on Apple Silicon; the surrounding .app gets re-signed by
# electron-builder, but signing the inner binary first avoids a kill on
# first spawn.
set -euo pipefail
cd "$(dirname "$0")"

python3 -m pip install --upgrade pip
pip install pyinstaller -r requirements.txt

pyinstaller --noconfirm --clean --onefile \
  --name laborster-sidecar \
  --collect-submodules laborster_bridge \
  --collect-all certifi \
  server.py

codesign --force --sign - dist/laborster-sidecar || true
echo "built: $(pwd)/dist/laborster-sidecar"
