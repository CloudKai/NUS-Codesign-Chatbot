#!/usr/bin/env sh
# Deprecated compatibility entry point.  Production images are built on the
# module EC2 host from a pinned Git commit; this repository has no ECR-based
# deployment.
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

exec "$ROOT/scripts/deploy_module_host.sh" "$@"
