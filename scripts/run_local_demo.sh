#!/usr/bin/env sh
# Local demo launcher — same full stack as scripts/start.sh.
set -eu
ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
exec sh "$ROOT/scripts/start.sh"
