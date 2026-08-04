#!/usr/bin/env sh
# Alias → scripts/start.sh (full API + UI stack). Prefer start.sh in docs.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
exec sh "$ROOT/scripts/start.sh"
