#!/usr/bin/env sh
# Render one module's host configuration, build locally, and start Compose.
# It reads the non-secret deployment contract from Parameter Store and the
# generated Cognito client secret from Secrets Manager. The application image
# is built from the already-verified Git checkout; no image registry is used.

set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

: "${MODULE_RUNTIME_CONFIG_PARAMETER:?MODULE_RUNTIME_CONFIG_PARAMETER is required}"
REGION="${AWS_REGION:?AWS_REGION is required}"

umask 077
config_json="$(aws ssm get-parameter --region "$REGION" \
  --name "$MODULE_RUNTIME_CONFIG_PARAMETER" --query 'Parameter.Value' --output text)"

config_value() {
  printf '%s' "$config_json" | jq -er --arg key "$1" '.[$key] | strings | select(length > 0)'
}

export AWS_REGION="$REGION"
export MODULE_ID="$(config_value module_id)"
export MODULE_CODE="$(config_value module_code)"
export MODULE_NAME="$(config_value module_name)"
export MODULE_PRODUCT_TITLE="$(config_value product_title)"
export MODULE_PROFILE_VERSION="$(config_value profile_version)"
export COURSE_MATERIALS_PREFIX="$(config_value course_materials_prefix)"
export PUBLIC_ORIGIN="$(config_value public_origin)"
export DSQL_ENDPOINT="$(config_value dsql_endpoint)"
export USER_UPLOADS_BUCKET="$(config_value user_uploads_bucket)"
export COURSE_MATERIALS_BUCKET="$(config_value course_materials_bucket)"
export KNOWLEDGE_BASE_ID="$(config_value knowledge_base_id)"
export GUARDRAIL_ID="$(config_value guardrail_id)"
export GUARDRAIL_VERSION="$(config_value guardrail_version)"
export AGENTCORE_RUNTIME_ARN="$(config_value agentcore_runtime_arn)"
export AGENTCORE_QUALIFIER="$(config_value agentcore_qualifier)"
export COGNITO_SECRET_ARN="$(config_value cognito_secret_arn)"
export APP_IMAGE="co-design-${MODULE_ID}:$(git rev-parse --verify HEAD)"

secret_json="$(aws secretsmanager get-secret-value --region "$REGION" \
  --secret-id "$COGNITO_SECRET_ARN" --query SecretString --output text)"
mkdir -p .streamlit
SECRET_JSON="$secret_json" python3 - <<'PY'
import json
import os
from pathlib import Path

secret = json.loads(os.environ["SECRET_JSON"])
required = ("client_id", "client_secret", "server_metadata_url", "redirect_uri")
missing = [name for name in required if not isinstance(secret.get(name), str) or not secret[name]]
if missing:
    raise SystemExit("Cognito secret is missing: " + ", ".join(missing))

def toml(value: str) -> str:
    return json.dumps(value)

Path(".streamlit/secrets.toml").write_text(
    "[auth]\n"
    + "client_id = " + toml(secret["client_id"]) + "\n"
    + "client_secret = " + toml(secret["client_secret"]) + "\n"
    + "server_metadata_url = " + toml(secret["server_metadata_url"]) + "\n"
    + "redirect_uri = " + toml(secret["redirect_uri"]) + "\n"
    + 'client_kwargs = { scope = "openid email profile", prompt = "login" }\n',
    encoding="utf-8",
)
PY
chmod 600 .streamlit/secrets.toml

python3 - <<'PY'
import os
from pathlib import Path

names = (
    "AWS_REGION", "MODULE_ID", "MODULE_CODE", "MODULE_NAME",
    "MODULE_PRODUCT_TITLE", "MODULE_PROFILE_VERSION", "COURSE_MATERIALS_PREFIX",
    "PUBLIC_ORIGIN", "DSQL_ENDPOINT", "USER_UPLOADS_BUCKET",
    "COURSE_MATERIALS_BUCKET", "KNOWLEDGE_BASE_ID", "GUARDRAIL_ID",
    "GUARDRAIL_VERSION", "AGENTCORE_RUNTIME_ARN", "AGENTCORE_QUALIFIER",
    "APP_IMAGE",
)
Path(".env").write_text(
    "".join(f"{name}={os.environ[name]}\n" for name in names), encoding="utf-8"
)
PY
chmod 600 .env

docker build --pull --build-arg "GIT_SHA=$(git rev-parse --verify HEAD)" -t "$APP_IMAGE" .
docker compose -f compose.prod.yaml up -d --remove-orphans
