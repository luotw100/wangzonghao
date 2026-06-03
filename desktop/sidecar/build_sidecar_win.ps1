# Freeze the sidecar into desktop/sidecar/dist/laborster-sidecar.exe.
# electron-builder then bundles it as an extra resource.
#
# Requires `uv` on PATH (the only build-time prereq; not shipped to users).
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

# Runtime deps + the PyInstaller toolchain both come from pyproject + uv.lock,
# the single source of truth. --frozen builds from the pinned lock so the
# released binary is reproducible.
uv sync --frozen --group build
uv run --no-sync pyinstaller --noconfirm --clean --onefile `
  --name laborster-sidecar `
  --collect-submodules laborster_bridge `
  --collect-all certifi `
  server.py

Write-Host "built: $PSScriptRoot\dist\laborster-sidecar.exe"
