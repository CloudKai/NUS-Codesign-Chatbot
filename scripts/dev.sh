#!/usr/bin/env sh
# Alias → scripts/start.sh. Same full stack as production local startup.
# Do not start Streamlit alone; Thinking Path needs the local API.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
exec sh "$ROOT/scripts/start.sh"
