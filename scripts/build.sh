#!/usr/bin/env sh
# =============================================================================
# scripts/build.sh — validation-only local gate
# =============================================================================
# Runs compileall + the full mock pytest suite. Does NOT initialize or modify
# the live student database. Use scripts/init_db.py explicitly when needed.
# =============================================================================
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

PYTHON="python3"
if [ -x "$ROOT/.venv/bin/python" ]; then
  PYTHON="$ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON="python3"
elif command -v python >/dev/null 2>&1; then
  PYTHON="python"
fi

echo "Using Python: $PYTHON"
export PYTHONPYCACHEPREFIX="${PYTHONPYCACHEPREFIX:-/private/tmp/co-design-pycache}"

"$PYTHON" -m compileall -q backend ui streamlit_app.py tests scripts
"$PYTHON" -m pytest -q
