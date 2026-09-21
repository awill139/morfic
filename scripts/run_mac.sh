#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
if [ ! -d .venv ]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
python -m pip install -U pip
python -m pip install -e .
echo "Starting Morfic at http://127.0.0.1:8765"
morfic
