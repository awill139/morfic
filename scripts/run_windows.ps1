$ErrorActionPreference = "Stop"
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Get-Command python -ErrorAction SilentlyContinue
if ($Python) { $Py = "python" }
elseif (Get-Command py -ErrorAction SilentlyContinue) { $Py = "py" }
else { throw "Python 3.11+ was not found." }

if (-not (Test-Path ".venv")) {
  if ($Py -eq "py") { & py -3 -m venv .venv } else { & python -m venv .venv }
}

$VenvPython = Join-Path $Root ".venv\Scripts\python.exe"
& $VenvPython -m pip install --upgrade pip
& $VenvPython -m pip install -e .

Write-Host ""
Write-Host "Starting Morfic at http://127.0.0.1:8765" -ForegroundColor Cyan
Write-Host "Press Ctrl+C to stop." -ForegroundColor Gray
& $VenvPython -m uvicorn morfic.app:app --host 127.0.0.1 --port 8765
