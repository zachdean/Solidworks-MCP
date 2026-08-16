#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

.venv/bin/python -m compileall -q solidworks_mcp
.venv/bin/python -m ruff check solidworks_mcp scripts

# Treat pytest's "no tests collected" (exit 5) as success too, so this
# gate still passes on branches where solidworks_mcp/tests/ is temporarily
# empty; any other nonzero exit still fails the gate.
rc=0
.venv/bin/python -m pytest -q || rc=$?
if [ "$rc" -ne 0 ] && [ "$rc" -ne 5 ]; then
    exit "$rc"
fi
