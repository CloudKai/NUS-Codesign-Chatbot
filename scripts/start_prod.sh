#!/usr/bin/env sh
# Run FastAPI and Streamlit together inside the production app container.
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

export USE_LOCAL_API="true"
export CO_DESIGN_API_URL="${CO_DESIGN_API_URL:-http://127.0.0.1:8000}"

DATA_DIR="${APP_DATA_DIR:-/app/data}"
SECRETS_FILE="/app/.streamlit/secrets.toml"
if [ ! -d "$DATA_DIR" ] || [ ! -w "$DATA_DIR" ]; then
  echo "Application data directory must exist and be writable: $DATA_DIR" >&2
  echo "On the host, create it and grant uid/gid 1000 ownership before startup." >&2
  exit 1
fi
if [ ! -f "$SECRETS_FILE" ] || [ ! -r "$SECRETS_FILE" ]; then
  echo "Streamlit secrets must be a readable file: $SECRETS_FILE" >&2
  exit 1
fi

API_PID=""
UI_PID=""

cleanup() {
  trap - EXIT INT TERM
  if [ -n "$UI_PID" ]; then
    kill -TERM "$UI_PID" 2>/dev/null || true
  fi
  if [ -n "$API_PID" ]; then
    kill -TERM "$API_PID" 2>/dev/null || true
  fi
  if [ -n "$UI_PID" ]; then
    wait "$UI_PID" 2>/dev/null || true
  fi
  if [ -n "$API_PID" ]; then
    wait "$API_PID" 2>/dev/null || true
  fi
}

trap cleanup EXIT
trap 'cleanup; exit 0' INT TERM

python -m uvicorn backend.api:app \
  --host 0.0.0.0 \
  --port 8000 &
API_PID=$!

echo "Waiting for FastAPI readiness..."
i=0
while [ "$i" -lt 60 ]; do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    wait "$API_PID" || status=$?
    echo "FastAPI exited before becoming ready." >&2
    exit "${status:-1}"
  fi
  if python - <<'PY'
import sys
import urllib.request

try:
    with urllib.request.urlopen(
        "http://127.0.0.1:8000/api/v1/ready", timeout=1
    ) as response:
        sys.exit(0 if response.status == 200 else 1)
except Exception:
    sys.exit(1)
PY
  then
    break
  fi
  i=$((i + 1))
  sleep 0.25
done

if [ "$i" -ge 60 ]; then
  echo "FastAPI did not become ready in time." >&2
  exit 1
fi

python -m streamlit run streamlit_app.py \
  --server.address 0.0.0.0 \
  --server.port 8501 \
  --server.headless true \
  --browser.gatherUsageStats false &
UI_PID=$!

echo "Production app services are running."
while :; do
  if ! kill -0 "$API_PID" 2>/dev/null; then
    status=0
    wait "$API_PID" || status=$?
    echo "FastAPI stopped; terminating Streamlit." >&2
    [ "$status" -ne 0 ] || status=1
    exit "$status"
  fi
  if ! kill -0 "$UI_PID" 2>/dev/null; then
    status=0
    wait "$UI_PID" || status=$?
    echo "Streamlit stopped; terminating FastAPI." >&2
    [ "$status" -ne 0 ] || status=1
    exit "$status"
  fi
  sleep 1
done
