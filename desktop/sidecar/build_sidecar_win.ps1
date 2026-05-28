# Freeze the sidecar into desktop/sidecar/dist/laborster-sidecar.exe.
# electron-builder then bundles it as an extra resource.
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

python -m pip install --upgrade pip
pip install pyinstaller -r requirements.txt

pyinstaller --noconfirm --clean --onefile `
  --name laborster-sidecar `
  --collect-submodules laborster_bridge `
  --collect-all certifi `
  server.py

Write-Host "built: $PSScriptRoot\dist\laborster-sidecar.exe"
