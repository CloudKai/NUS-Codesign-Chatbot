#!/usr/bin/env sh
# DuckDNS updater for the EC2 host (not the application container).
# Install under /home/ubuntu/duckdns/ alongside a protected duck.env.
#
# duck.env (mode 600, not in Git):
#   DUCKDNS_TOKEN=<token>
#   DUCKDNS_DOMAIN=cde2300chatbot
#
# Cron (every 5 minutes):
#   */5 * * * * /home/ubuntu/duckdns/duck.sh >/dev/null 2>&1
set -eu

DIR="$(CDPATH= cd -- "$(dirname "$0")" && pwd)"
ENV_FILE="${DIR}/duck.env"

if [ ! -f "${ENV_FILE}" ]; then
  echo "missing duck.env" >&2
  exit 1
fi

# shellcheck disable=SC1090
. "${ENV_FILE}"

if [ -z "${DUCKDNS_TOKEN:-}" ] || [ -z "${DUCKDNS_DOMAIN:-}" ]; then
  echo "DUCKDNS_TOKEN and DUCKDNS_DOMAIN are required" >&2
  exit 1
fi

# Empty ip= lets DuckDNS detect the caller public IPv4.
# Never echo the token.
STATUS="$(
  curl -fsS "https://www.duckdns.org/update?domains=${DUCKDNS_DOMAIN}&token=${DUCKDNS_TOKEN}&ip="
)" || STATUS="curl-failed"

echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) duckdns=${STATUS}" >>"${DIR}/duck.log"
