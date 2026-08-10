#!/usr/bin/env sh
# Run the headed, manually authenticated browser smoke checks for this project.
#
# This is intentionally not a CI test. Cognito authentication is a real external
# identity boundary and this script does not inject cookies, credentials, or a
# production authentication bypass. Run it only after `sh scripts/start.sh` and
# sign in through the displayed Cognito Hosted UI yourself.
set -eu

TASK_ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
TASK_PWCLI="${PWCLI:-${HOME}/.codex/skills/playwright/scripts/playwright_cli.sh}"
TASK_SESSION="co-design-browser-smoke"
TASK_OUTPUT="$TASK_ROOT/output/playwright/browser-smoke"
TASK_UI_URL="${CO_DESIGN_UI_URL:-http://127.0.0.1:8501}"

if ! command -v npx >/dev/null 2>&1; then
  echo "npx is required for the Playwright CLI. Install Node.js/npm first." >&2
  exit 1
fi
if [ ! -x "$TASK_PWCLI" ]; then
  echo "Playwright CLI wrapper not found: $TASK_PWCLI" >&2
  echo "Set PWCLI to the installed playwright_cli.sh path." >&2
  exit 1
fi
if ! curl --fail --silent "$TASK_UI_URL/_stcore/health" >/dev/null; then
  echo "Local Streamlit is not ready at $TASK_UI_URL. Start it with: sh scripts/start.sh" >&2
  exit 1
fi

mkdir -p "$TASK_OUTPUT"
cd "$TASK_OUTPUT"

echo "Opening the signed-out UI at desktop width."
"$TASK_PWCLI" --session "$TASK_SESSION" open "$TASK_UI_URL" --headed
"$TASK_PWCLI" --session "$TASK_SESSION" resize 1440 960
"$TASK_PWCLI" --session "$TASK_SESSION" snapshot
"$TASK_PWCLI" --session "$TASK_SESSION" screenshot

cat <<'CHECKLIST'

Manual authenticated continuation (do not put credentials in this script):
  1. In the headed browser, press "Sign in or create an account" and complete
     the real Cognito Hosted UI flow.
  2. Confirm the returned workspace has the expected profile and a notebook.
  3. Upload a small .txt source, select it, ask a grounded question, and open
     its [S1] citation preview.
  4. Send a second Focus message, press Next, and confirm the Evidence stage.
  5. Reload once; verify chat, citation, and stage remain. Then delete the
     disposable notebook and sign out.
  6. Return here and press Enter to capture the authenticated mobile evidence.

The script never fabricates a Cognito session, so this continuation requires
an intentionally approved live Cognito smoke test. Ctrl-C exits without
changing application data.
CHECKLIST
read -r TASK_UNUSED

echo "Capturing the same authenticated session at 390 px mobile width."
"$TASK_PWCLI" --session "$TASK_SESSION" resize 390 844
"$TASK_PWCLI" --session "$TASK_SESSION" snapshot
"$TASK_PWCLI" --session "$TASK_SESSION" screenshot
"$TASK_PWCLI" --session "$TASK_SESSION" console error

echo "Artifacts are in $TASK_OUTPUT. Close the browser with:"
echo "  $TASK_PWCLI --session $TASK_SESSION close"
