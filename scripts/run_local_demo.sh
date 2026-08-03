#!/usr/bin/env sh
# Start the local FastAPI/LangGraph backend and Streamlit UI together.
set -eu

PYTHON="python"
if [ -x ".venv/bin/python" ]; then
  PYTHON=".venv/bin/python"
fi

export USE_LOCAL_API="true"
export CO_DESIGN_API_URL="${CO_DESIGN_API_URL:-http://127.0.0.1:8000}"

"$PYTHON" -m uvicorn backend.api:app --host 127.0.0.1 --port 8000 &
API_PID=$!

cleanup() {
  kill "$API_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM

"$PYTHON" -m streamlit run streamlit_app.py \
  --server.address 127.0.0.1 \
  --server.port 8501 \
  --browser.gatherUsageStats false
