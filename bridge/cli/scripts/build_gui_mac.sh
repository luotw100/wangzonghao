#!/usr/bin/env bash
# Build LaborsterBridge.app and zip it. Runs on a macOS runner; the
# runner's native arch decides x64 (macos-13) vs arm64 (macos-14).
# Ad-hoc codesign is REQUIRED on Apple Silicon (unsigned code is killed
# by the kernel); harmless on Intel. No notarization (no Apple account)
# — users run `xattr -cr LaborsterBridge.app` after download.
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m pip install --upgrade pip
pip install pyinstaller pywebview
pip install -e .

pyinstaller --noconfirm --clean --windowed \
  --name LaborsterBridge \
  --icon laborster_bridge/gui/assets/LaborsterBridge.icns \
  --osx-bundle-identifier com.laborster.bridge \
  --add-data "laborster_bridge/gui/web:laborster_bridge/gui/web" \
  --add-data "laborster_bridge/gui/assets:laborster_bridge/gui/assets" \
  --collect-all webview \
  scripts/gui_launcher.py

APP="dist/LaborsterBridge.app"
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP" || true

ARCH="$(uname -m)"
case "$ARCH" in
  arm64) TAG="arm64" ;;
  x86_64) TAG="x64" ;;
  *) TAG="$ARCH" ;;
esac
( cd dist && ditto -c -k --keepParent "LaborsterBridge.app" "LaborsterBridge-mac-${TAG}.zip" )
echo "built: dist/LaborsterBridge-mac-${TAG}.zip"
