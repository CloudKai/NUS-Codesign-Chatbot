#!/usr/bin/env sh
# Plan or apply the CloudFormation stacks under infra/aws/.
#
# Default is a DRY RUN that makes no AWS call: it prints the plan and the exact
# commands it would run. --validate-remote adds read-only validate-template
# calls. Applying needs BOTH --apply and --confirm-account <12-digit id>, and
# the id must match the caller's account. Credentials come from the usual AWS
# CLI chain (instance role or SSO); none are read from or written to files here.
set -eu

ROOT="$(CDPATH= cd -- "$(dirname "$0")/../.." && pwd)"
INFRA="$ROOT/infra/aws"

usage() {
  cat <<'EOF'
Usage: scripts/aws/deploy_stack.sh [options]

Dry run by default (no AWS call). Options:
  --stack app|edge|all      Stack to plan or deploy (default: all)
  --app-params FILE         Key=Value lines for infra/aws/app-tier.yaml
  --edge-params FILE        Key=Value lines for infra/aws/edge-monitoring.yaml
  --app-region REGION       Region for the app stack (default: us-west-2)
  --validate-remote         Dry run only: also call aws cloudformation validate-template (read only)
  --apply                   Create or update the stacks (needs --confirm-account)
  --confirm-account ID      12-digit AWS account id that must match the caller
  --help                    Show this help

Applying needs both --apply and --confirm-account. The edge stack always
deploys to us-east-1 because CloudFront metrics live there.
Example parameter files: infra/aws/parameters.*.example.txt
EOF
}

STACK="all"
APP_PARAMS=""
EDGE_PARAMS=""
APP_REGION="us-west-2"
APPLY="no"
VALIDATE_REMOTE="no"
CONFIRM_ACCOUNT=""

while [ "$#" -gt 0 ]; do
  case "$1" in
    --help|-h) usage; exit 0 ;;
    --stack) STACK="${2:-}"; shift 2 || { echo "--stack needs a value" >&2; exit 2; } ;;
    --app-params) APP_PARAMS="${2:-}"; shift 2 || { echo "--app-params needs a value" >&2; exit 2; } ;;
    --edge-params) EDGE_PARAMS="${2:-}"; shift 2 || { echo "--edge-params needs a value" >&2; exit 2; } ;;
    --app-region) APP_REGION="${2:-}"; shift 2 || { echo "--app-region needs a value" >&2; exit 2; } ;;
    --confirm-account) CONFIRM_ACCOUNT="${2:-}"; shift 2 || { echo "--confirm-account needs a value" >&2; exit 2; } ;;
    --validate-remote) VALIDATE_REMOTE="yes"; shift ;;
    --apply) APPLY="yes"; shift ;;
    *) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
  esac
done

case "$STACK" in app|edge|all) ;; *) echo "--stack must be app, edge or all" >&2; exit 2 ;; esac

if [ "$APPLY" = "yes" ] && [ -z "$CONFIRM_ACCOUNT" ]; then
  echo "Refusing to apply: --apply also needs --confirm-account <12-digit-id>." >&2
  exit 2
fi
if [ "$APPLY" != "yes" ] && [ -n "$CONFIRM_ACCOUNT" ]; then
  echo "Refusing to continue: --confirm-account is only valid together with --apply." >&2
  exit 2
fi
if [ -n "$CONFIRM_ACCOUNT" ]; then
  case "$CONFIRM_ACCOUNT" in
    *[!0-9]*|"") echo "--confirm-account must be exactly 12 digits." >&2; exit 2 ;;
  esac
  if [ "${#CONFIRM_ACCOUNT}" -ne 12 ]; then
    echo "--confirm-account must be exactly 12 digits." >&2
    exit 2
  fi
fi

check_params() {
  # $1 label, $2 file
  if [ "$APPLY" = "yes" ] && [ -z "$2" ]; then
    echo "--$1-params FILE is required to apply the $1 stack." >&2
    exit 2
  fi
  if [ -n "$2" ] && [ ! -r "$2" ]; then
    echo "Parameter file not readable: $2" >&2
    exit 2
  fi
  if [ -n "$2" ] && grep -q 'REPLACE_ME' "$2"; then
    echo "Parameter file still contains REPLACE_ME placeholders: $2" >&2
    exit 2
  fi
}

# Print the Key=Value overrides (comments and blank lines removed).
overrides() {
  grep -v '^[[:space:]]*#' "$1" | grep -v '^[[:space:]]*$' || true
}

run_stack() {
  # $1 label, $2 template, $3 stack name, $4 region, $5 params file, $6 capabilities
  label="$1"; template="$2"; name="$3"; region="$4"; params="$5"; caps="$6"
  echo "== $label stack: $name ($region)"
  echo "   template: $template"
  if [ -n "$params" ]; then
    echo "   parameters (names only):"
    overrides "$params" | cut -d= -f1 | sed 's/^/     - /'
  else
    echo "   parameters: none supplied (needed only to apply)"
  fi
  if [ "$APPLY" = "yes" ]; then
    # shellcheck disable=SC2046
    aws cloudformation deploy --region "$region" --stack-name "$name" \
      --template-file "$template" --no-fail-on-empty-changeset \
      --capabilities $caps \
      --parameter-overrides $(overrides "$params" | tr '\n' ' ')
    return
  fi
  echo "   would run: aws cloudformation deploy --region $region --stack-name $name --template-file $template --capabilities $caps --parameter-overrides <from params file>"
  if [ "$VALIDATE_REMOTE" = "yes" ]; then
    aws cloudformation validate-template --region "$region" --template-body "file://$template" >/dev/null
    echo "   validate-template: ok"
  fi
}

if [ "$APPLY" = "yes" ]; then
  [ "$STACK" != "edge" ] && check_params app "$APP_PARAMS"
  [ "$STACK" != "app" ] && check_params edge "$EDGE_PARAMS"
  caller="$(aws sts get-caller-identity --query Account --output text)"
  if [ "$caller" != "$CONFIRM_ACCOUNT" ]; then
    echo "Refusing to apply: the caller's account does not match --confirm-account." >&2
    exit 3
  fi
  echo "APPLY mode: changes will be made in the confirmed account."
else
  echo "DRY RUN: no stack will be created or changed. Add --apply --confirm-account <12-digit-id> to apply."
  [ -n "$APP_PARAMS" ] && check_params app "$APP_PARAMS"
  [ -n "$EDGE_PARAMS" ] && check_params edge "$EDGE_PARAMS"
fi

if [ "$STACK" != "edge" ]; then
  run_stack app "$INFRA/app-tier.yaml" co-design-app "$APP_REGION" "$APP_PARAMS" CAPABILITY_IAM
fi
if [ "$STACK" != "app" ]; then
  run_stack edge "$INFRA/edge-monitoring.yaml" co-design-edge us-east-1 "$EDGE_PARAMS" CAPABILITY_IAM
fi

if [ "$APPLY" != "yes" ]; then
  echo "DRY RUN complete. Nothing was changed."
fi
