#!/usr/bin/env bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

# Optional official distribution build. The public source remains community-configured;
# the packaged website build can default to the hosted orchestrator without embedding secrets.
DIST_FILE="$ROOT/morfic/distribution.json"
DIST_BACKUP="$(mktemp)"
cp "$DIST_FILE" "$DIST_BACKUP"
restore_distribution() { cp "$DIST_BACKUP" "$DIST_FILE"; rm -f "$DIST_BACKUP"; }
trap restore_distribution EXIT
# MORFIC_* is preferred; the legacy PERSONAL_SOFTWARE_* spelling is still accepted.
DISTRIBUTION="${MORFIC_DISTRIBUTION:-${PERSONAL_SOFTWARE_DISTRIBUTION:-community}}"
OFFICIAL_URL="${MORFIC_OFFICIAL_URL:-${PERSONAL_SOFTWARE_OFFICIAL_URL:-}}"
if [[ "$DISTRIBUTION" == "official" ]]; then
  : "${OFFICIAL_URL:?Set MORFIC_OFFICIAL_URL for an official build}"
  python3 - "$DIST_FILE" "$OFFICIAL_URL" <<'PYDIST'
import json,sys
p=sys.argv[1]; url=sys.argv[2].rstrip('/')
open(p,'w',encoding='utf-8').write(json.dumps({'mode':'official','official_base_url':url},indent=2))
PYDIST
fi

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  for candidate in python3.13 python3.12 python3.11; do
    if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
      PYTHON_BIN="$candidate"
      break
    fi
  done
fi
if ! "$PYTHON_BIN" -c 'import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)' 2>/dev/null; then
  echo "Could not find Python >=3.11. Set PYTHON_BIN to a Python 3.11+ interpreter." >&2
  exit 1
fi

rm -rf .venv-build
"$PYTHON_BIN" -m venv .venv-build
source .venv-build/bin/activate
python -m pip install --upgrade pip
python -m pip install -e '.[desktop,build]'
python scripts/make_icon.py

# Fail early if the interpreter itself lacks SQLite support; the packaged runtime requires it.
python - <<'PY2'
import sqlite3, sys
print(f"Building with Python {sys.version.split()[0]} ({sys.executable}); SQLite {sqlite3.sqlite_version}")
PY2

# Optional Developer ID signing. Without MORFIC_CODESIGN_IDENTITY the app is ad-hoc signed,
# which macOS Gatekeeper warns about on other machines.
SIGN_ARGS=()
if [[ -n "${MORFIC_CODESIGN_IDENTITY:-}" ]]; then
  SIGN_ARGS+=(--codesign-identity "$MORFIC_CODESIGN_IDENTITY" --osx-entitlements-file "$ROOT/packaging/entitlements.plist")
fi

rm -rf build dist
pyinstaller \
  --noconfirm \
  --clean \
  --windowed \
  --name 'Morfic' \
  --icon './build-assets/app.icns' \
  --collect-all morfic \
  --collect-all fastapi \
  --collect-all starlette \
  --collect-all pydantic \
  --collect-all pydantic_core \
  --collect-all httpx \
  --collect-all httpcore \
  --collect-all keyring \
  --collect-all uvicorn \
  --collect-all webview \
  --collect-all sqlite3 \
  --hidden-import _sqlite3 \
  ${SIGN_ARGS[@]+"${SIGN_ARGS[@]}"} \
  ./packaging/desktop_entry.py

APP='dist/Morfic.app'
DMG='dist/Morfic.dmg'
if [[ ! -d "$APP" ]]; then
  echo "Expected app bundle was not created: $APP" >&2
  exit 1
fi
rm -f "$DMG"
DMG_ROOT='build/dmg-root'
rm -rf "$DMG_ROOT"
mkdir -p "$DMG_ROOT"
ditto "$APP" "$DMG_ROOT/Morfic.app"
ln -s /Applications "$DMG_ROOT/Applications"
hdiutil create \
  -volname 'Morfic' \
  -srcfolder "$DMG_ROOT" \
  -ov \
  -format UDZO \
  "$DMG"

# Optional notarization (requires MORFIC_CODESIGN_IDENTITY and a notarytool keychain profile,
# created once with: xcrun notarytool store-credentials <profile> ...).
if [[ -n "${MORFIC_CODESIGN_IDENTITY:-}" ]]; then
  codesign --force --sign "$MORFIC_CODESIGN_IDENTITY" --timestamp "$DMG"
  if [[ -n "${MORFIC_NOTARY_PROFILE:-}" ]]; then
    xcrun notarytool submit "$DMG" --keychain-profile "$MORFIC_NOTARY_PROFILE" --wait
    xcrun stapler staple "$DMG"
  else
    echo "MORFIC_NOTARY_PROFILE not set: DMG is signed but not notarized." >&2
  fi
fi

echo
echo "Built: $ROOT/$APP"
echo "Built: $ROOT/$DMG"
