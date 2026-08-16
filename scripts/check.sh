#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

.venv/bin/python -m compileall -q solidworks_mcp
.venv/bin/python -m ruff check solidworks_mcp scripts

.venv/bin/python -m pytest -q
