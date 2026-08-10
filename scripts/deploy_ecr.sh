#!/usr/bin/env sh
# Pull a prebuilt linux/arm64 app image from ECR and restart production Compose.
#
# Required host environment (do not commit secrets):
#   AWS_REGION          (default us-west-2)
#   ECR_REGISTRY        e.g. 123456789012.dkr.ecr.us-west-2.amazonaws.com
#   APP_IMAGE           full image URI including immutable tag
#
# Prefer an EC2 instance IAM role over long-lived access keys.
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

REGION="${AWS_REGION:-us-west-2}"
COMPOSE_FILE="${COMPOSE_FILE:-compose.prod.yaml}"

if [ -z "${APP_IMAGE:-}" ]; then
  echo "APP_IMAGE must be set to the ECR image URI:tag" >&2
  exit 1
fi
if [ -z "${ECR_REGISTRY:-}" ]; then
  # Derive registry host from APP_IMAGE when possible.
  ECR_REGISTRY="${APP_IMAGE%%/*}"
fi

echo "Logging into ECR registry ${ECR_REGISTRY} (${REGION})..."
aws ecr get-login-password --region "${REGION}" \
  | docker login --username AWS --password-stdin "${ECR_REGISTRY}"

echo "Pulling ${APP_IMAGE}..."
docker compose -f "${COMPOSE_FILE}" pull

echo "Starting services..."
docker compose -f "${COMPOSE_FILE}" up -d

echo "Deployment refresh complete."
