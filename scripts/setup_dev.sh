#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

python3 -m venv .venv

# Windows venvs put the interpreter in Scripts/, not bin/ (see scripts/check.sh).
PY=.venv/bin/python
[ -x "$PY" ] || PY=.venv/Scripts/python.exe

"$PY" -m pip install --upgrade pip
"$PY" -m pip install -r requirements.txt -r requirements-dev.txt

echo "Dev environment ready. Activate with: source .venv/bin/activate"
