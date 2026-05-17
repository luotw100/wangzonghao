# Build LaborsterBridge.exe (single-file, double-click, no install).
# Run on a Windows runner/host. Produces dist/LaborsterBridge.exe.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")

python -m pip install --upgrade pip
pip install pyinstaller pywebview pythonnet
pip install -e .

pyinstaller --noconfirm --clean --onefile --windowed `
  --name LaborsterBridge `
  --icon laborster_bridge/gui/assets/LaborsterBridge.ico `
  --add-data "laborster_bridge/gui/web;laborster_bridge/gui/web" `
  --add-data "laborster_bridge/gui/assets;laborster_bridge/gui/assets" `
  --collect-all webview `
  --collect-all clr_loader `
  scripts/gui_launcher.py

Write-Host "built: dist/LaborsterBridge.exe"
