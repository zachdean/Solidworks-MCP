#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

# venv layout differs by platform, and SolidWorks itself only runs on Windows,
# so the developer most likely to need this gate is the one on Scripts/.
PY=.venv/bin/python
[ -x "$PY" ] || PY=.venv/Scripts/python.exe
[ -x "$PY" ] || { echo "No venv found. Run scripts/setup_dev.sh first." >&2; exit 1; }

"$PY" -m compileall -q solidworks_mcp
"$PY" -m ruff check solidworks_mcp scripts
"$PY" scripts/check_api_docs.py

"$PY" -m pytest -q
