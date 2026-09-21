$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
Set-Location $Root

# Optional official website build. This writes only the public orchestrator URL, never provider secrets.
$DistFile = Join-Path $Root "morfic\distribution.json"
$DistBackup = Get-Content $DistFile -Raw
try {
  # MORFIC_* is preferred; the legacy PERSONAL_SOFTWARE_* spelling is still accepted.
  $Distribution = if ($env:MORFIC_DISTRIBUTION) { $env:MORFIC_DISTRIBUTION } else { $env:PERSONAL_SOFTWARE_DISTRIBUTION }
  $OfficialUrl = if ($env:MORFIC_OFFICIAL_URL) { $env:MORFIC_OFFICIAL_URL } else { $env:PERSONAL_SOFTWARE_OFFICIAL_URL }
  if ($Distribution -eq "official") {
    if (-not $OfficialUrl) { throw "Set MORFIC_OFFICIAL_URL for an official build." }
    @{ mode = "official"; official_base_url = $OfficialUrl.TrimEnd('/') } | ConvertTo-Json | Set-Content $DistFile -Encoding UTF8
  }

$Candidates = @("py -3.13", "py -3.12", "py -3.11", "python")
$PythonCmd = $null
foreach ($Candidate in $Candidates) {
  try {
    $parts = $Candidate.Split(" ")
    $exe = $parts[0]
    $args = @()
    if ($parts.Length -gt 1) { $args += $parts[1..($parts.Length-1)] }
    & $exe @args -c "import sys; raise SystemExit(0 if sys.version_info >= (3,11) else 1)" 2>$null
    if ($LASTEXITCODE -eq 0) { $PythonCmd = $Candidate; break }
  } catch {}
}
if (-not $PythonCmd) { throw "Could not find Python >=3.11. Install Python 3.11+ to build the installer." }

Remove-Item -Recurse -Force .\.venv-build -ErrorAction SilentlyContinue
$parts = $PythonCmd.Split(" ")
$exe = $parts[0]
$args = @()
if ($parts.Length -gt 1) { $args += $parts[1..($parts.Length-1)] }
& $exe @args -m venv .venv-build
& .\.venv-build\Scripts\python.exe -m pip install --upgrade pip
& .\.venv-build\Scripts\python.exe -m pip install -e ".[desktop,build]"
& .\.venv-build\Scripts\python.exe .\scripts\make_icon.py
& .\.venv-build\Scripts\python.exe -c "import sqlite3,sys; print('Building with Python', sys.version.split()[0], 'SQLite', sqlite3.sqlite_version)"

Remove-Item -Recurse -Force .\build -ErrorAction SilentlyContinue
Remove-Item -Recurse -Force .\dist -ErrorAction SilentlyContinue

& .\.venv-build\Scripts\pyinstaller.exe `
  --noconfirm `
  --clean `
  --onefile `
  --windowed `
  --name "Morfic" `
  --icon ".\build-assets\app.ico" `
  --collect-all morfic `
  --collect-all fastapi `
  --collect-all starlette `
  --collect-all pydantic `
  --collect-all pydantic_core `
  --collect-all httpx `
  --collect-all httpcore `
  --collect-all keyring `
  --collect-all uvicorn `
  --collect-all webview `
  --collect-all sqlite3 `
  --hidden-import _sqlite3 `
  .\packaging\desktop_entry.py

Write-Host ""
Write-Host "Built: $Root\dist\Morfic.exe" -ForegroundColor Green
}
finally {
  Set-Content $DistFile -Value $DistBackup -Encoding UTF8
}
