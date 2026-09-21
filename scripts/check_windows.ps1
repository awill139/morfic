$ErrorActionPreference = "Continue"
Write-Host "Morfic v0.6 - Windows readiness" -ForegroundColor Cyan
Write-Host ""

function Show-Tool($name, $command) {
  $found = Get-Command $command -ErrorAction SilentlyContinue
  if ($found) { Write-Host "[OK] $name -> $($found.Source)" -ForegroundColor Green; return $true }
  Write-Host "[--] $name not found" -ForegroundColor Yellow; return $false
}

$python = Show-Tool "Python" "python"
if (-not $python) { $python = Show-Tool "Python launcher" "py" }
$git = Show-Tool "Git" "git"
$podman = Show-Tool "Podman" "podman"
$docker = Show-Tool "Docker" "docker"
$wsl = Show-Tool "WSL" "wsl"

Write-Host ""
if (-not $python) { Write-Host "Python 3.11+ is required." -ForegroundColor Red }
if (-not $git) { Write-Host "Git is required for curated GitHub apps." -ForegroundColor Red }
if (-not ($podman -or $docker)) {
  Write-Host "The bundled demo repos and generated apps can run, but untrusted GitHub apps are blocked until Podman or Docker is installed." -ForegroundColor Yellow
  Write-Host "The runtime intentionally will not execute untrusted repositories directly on Windows." -ForegroundColor Yellow
}
Write-Host ""
Write-Host "OpenAI or Anthropic must be configured in the in-app AI Settings before resolving, generating, repairing, or modifying software." -ForegroundColor Gray
