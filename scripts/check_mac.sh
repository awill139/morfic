#!/usr/bin/env bash
set -u

echo "Morfic v0.6 - macOS check"
for cmd in python3 git; do
  if command -v "$cmd" >/dev/null 2>&1; then
    echo "[OK] $cmd: $(command -v "$cmd")"
  else
    echo "[MISSING] $cmd"
  fi
done
if command -v podman >/dev/null 2>&1; then
  echo "[OK] Podman: $(command -v podman)"
elif command -v docker >/dev/null 2>&1; then
  echo "[OK] Docker: $(command -v docker)"
else
  echo "[OPTIONAL FOR BUNDLED DEMOS / REQUIRED FOR UNTRUSTED REPOS] Install Podman Desktop or Docker Desktop."
fi
python3 - <<'PY'
import sys
print('[OK]' if sys.version_info >= (3,11) else '[TOO OLD]', 'Python', sys.version.split()[0])
PY
