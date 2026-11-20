#!/usr/bin/env sh
# Start the local mock app without taking the default browser port 8080.
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [ ! -x "$ROOT/.venv/bin/python" ]; then
  echo "Create the project environment first. See README.md, Run locally." >&2
  exit 1
fi
if [ ! -f "$ROOT/frontend/dist/index.html" ]; then
  echo "Build the React app first with: npm run build --prefix frontend" >&2
  exit 1
fi
for command in caddy sed; do
  if ! command -v "$command" >/dev/null 2>&1; then
    echo "Required command not found: $command" >&2
    exit 1
  fi
done

export GUEST_ACCESS_ENABLED=true
export USE_LOCAL_API=true
export MODEL_PROVIDER=mock
export MOCK_OPENAI=true
export COACHING_MODEL_PROVIDER=mock
export REVIEW_DEEP_MODEL_PROVIDER=mock
export AGENTCORE_MODEL_PROVIDER=mock
export CO_DESIGN_API_URL=http://127.0.0.1:8000
export CO_DESIGN_PUBLIC_API_URL=http://127.0.0.1:8081
export CO_DESIGN_UI_URL=http://127.0.0.1:8081
export KNOWLEDGE_BASE_ID=

CONFIG="$(mktemp "${TMPDIR:-/tmp}/codesign-caddy-8081.XXXXXX")"
printf '{\n admin off\n}\n' > "$CONFIG"
sed 's/127\.0\.0\.1:8080/127.0.0.1:8081/g' "$ROOT/Caddyfile.local" >> "$CONFIG"

API_PID=
CADDY_PID=
STREAMLIT_PID=
cleanup() {
  [ -z "$STREAMLIT_PID" ] || kill "$STREAMLIT_PID" 2>/dev/null || true
  [ -z "$CADDY_PID" ] || kill "$CADDY_PID" 2>/dev/null || true
  [ -z "$API_PID" ] || kill "$API_PID" 2>/dev/null || true
  rm -f "$CONFIG"
}
trap cleanup EXIT
trap 'exit 0' INT TERM

echo "Starting local mock app at http://127.0.0.1:8081/"
"$ROOT/.venv/bin/python" -m uvicorn backend.api:app --host 127.0.0.1 --port 8000 &
API_PID=$!

ready=false
attempt=0
while [ "$attempt" -lt 60 ]; do
  if curl -fsS http://127.0.0.1:8000/api/v1/ready >/dev/null 2>&1; then
    ready=true
    break
  fi
  attempt=$((attempt + 1))
  sleep 0.25
done
if [ "$ready" != true ]; then
  echo "FastAPI did not become ready. Check port 8000 and the startup logs." >&2
  exit 1
fi

caddy run --config "$CONFIG" --adapter caddyfile &
CADDY_PID=$!
"$ROOT/.venv/bin/python" -m streamlit run streamlit_app.py \
  --server.address 127.0.0.1 \
  --server.port 8501 \
  --server.baseUrlPath streamlit \
  --server.headless true \
  --browser.gatherUsageStats false &
STREAMLIT_PID=$!

wait "$API_PID"
