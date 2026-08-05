#!/usr/bin/env sh
# =============================================================================
# scripts/start.sh — single command to run the full local Co-design stack
# =============================================================================
# Starts:
#   1) FastAPI coaching API on http://127.0.0.1:8000
#   2) Streamlit UI on http://127.0.0.1:8501
#
# Always sets USE_LOCAL_API=true so Thinking Path stage advancement and selected
# image grounding work. Prefer this over starting Streamlit alone.
#
# Prerequisites: project .venv with requirements.txt installed; optional .env
# from .env.example (MODEL_PROVIDER=mock by default).
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

export USE_LOCAL_API="true"
export CO_DESIGN_API_URL="${CO_DESIGN_API_URL:-http://127.0.0.1:8000}"

echo "Starting Co-design Chatbot"
echo "  API:  http://127.0.0.1:8000/api/v1/health"
echo "  Ready: http://127.0.0.1:8000/api/v1/ready"
echo "  UI:   http://127.0.0.1:8501"
echo "  Python: $PYTHON"
echo "  USE_LOCAL_API=true (required for Thinking Path + image coaching)"
echo ""

"$PYTHON" -m uvicorn backend.api:app --host 127.0.0.1 --port 8000 &
API_PID=$!

cleanup() {
  kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "Waiting for API readiness…"
READY_URL="${CO_DESIGN_API_URL}/api/v1/ready"
i=0
while [ "$i" -lt 60 ]; do
  if "$PYTHON" - <<PY
import sys
import urllib.request
try:
    with urllib.request.urlopen("$READY_URL", timeout=1) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
  then
    echo "API is ready."
    break
  fi
  i=$((i + 1))
  sleep 0.25
done
if [ "$i" -ge 60 ]; then
  echo "API did not become ready in time." >&2
  exit 1
fi

"$PYTHON" -m streamlit run streamlit_app.py \
  --server.address 127.0.0.1 \
  --server.port 8501 \
  --browser.gatherUsageStats false
