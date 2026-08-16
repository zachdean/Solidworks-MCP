#!/usr/bin/env bash
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."

.venv/bin/python -m compileall -q solidworks_mcp
.venv/bin/python -m ruff check solidworks_mcp scripts

# solidworks_mcp currently still imports win32com unconditionally at package
# load time (fixed in sw-n50.2), so no test can be collected under
# solidworks_mcp/tests/ yet. Treat pytest's "no tests collected" (exit 5) as
# success here; any other nonzero exit still fails the gate.
rc=0
.venv/bin/python -m pytest -q || rc=$?
if [ "$rc" -ne 0 ] && [ "$rc" -ne 5 ]; then
    exit "$rc"
fi
