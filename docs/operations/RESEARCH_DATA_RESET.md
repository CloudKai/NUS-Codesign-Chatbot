# Five-phase research data reset

## Why this is explicit

The former six-stage journey and the current five research-aligned phases do
not have a defensible one-to-one semantic mapping. The application therefore
does not silently relabel existing learning records. A non-empty database must
contain the exact `cde2300-five-phase-v1` workflow marker before readiness
succeeds.

The reset command removes learning content and research records while
preserving users, Cognito attribution, persisted roles, and OAuth/session
tables. It never runs during normal application startup.

## SQLite dry run

Stop FastAPI and Streamlit so the inventory remains stable, then write a reset
manifest without changing any data:

```sh
.venv/bin/python scripts/reset_learning_data.py \
  --provider sqlite \
  --database data/co_design.sqlite3 \
  --files-root data/files \
  --manifest /private/tmp/cde2300-reset-manifest.json
```

Confirm the resolved database and files root, preserved user/staff counts,
every deletion count, notebook ID, owner ID, and managed object count. The
manifest contains internal identifiers and local paths; do not commit or share
it as research data.

## SQLite apply and recovery

Only after the dry run has been reviewed and the loss of notebook learning data
has been approved, rerun with the saved manifest and exact phrase:

```sh
.venv/bin/python scripts/reset_learning_data.py \
  --provider sqlite \
  --manifest /private/tmp/cde2300-reset-manifest.json \
  --apply \
  --confirmation RESET-CDE2300-LEARNING-DATA
```

The command rejects a modified manifest or any learning-data change since the
inventory. Before deletion it creates a WAL-safe SQLite backup under
`reset-backups/`; managed notebook files move to a reset-specific directory
under `reset-quarantine/`. The result prints both paths. Retain them until the
new workflow has been validated.

To roll back, stop both services, preserve the post-reset database separately,
restore the printed `.bak` file as the configured database, and move the
printed quarantined `users/.../notebooks/...` prefixes back under the configured
files root. Verify the database with SQLite integrity checks before restarting.

## Aurora DSQL and S3

Bootstrap the additive DSQL schema first with the admin-only
`scripts/init_dsql.py`. Bootstrap initializes the workflow marker only when the
database contains zero notebooks. If learning data already exists without the
exact marker, it leaves that data and marker unchanged and directs the operator
to this reviewed reset procedure with a non-zero exit status. Create the
inventory using admin IAM
authentication. From a laptop, `sslmode=verify-full` with `sslrootcert=system`
often fails (`SSL error: certificate verify failed`) because OpenSSL does not
use the macOS Keychain. Point at Amazon Root CA 1 first (same as the
CloudShell / laptop checklist in [`docs/deploy/AWS_STATELESS_EC2.md`](../deploy/AWS_STATELESS_EC2.md)):

```sh
curl -fsSL -o "$HOME/AmazonRootCA1.pem" \
  https://www.amazontrust.com/repository/AmazonRootCA1.pem
export DSQL_SSLROOTCERT="$HOME/AmazonRootCA1.pem"

.venv/bin/python scripts/reset_learning_data.py \
  --provider dsql \
  --endpoint "$DSQL_ENDPOINT" \
  --region "$AWS_REGION" \
  --bucket "$USER_UPLOADS_BUCKET" \
  --manifest /private/tmp/cde2300-dsql-reset-manifest.json
```

Inspect every DSQL row count and every owner-scoped S3 prefix. Applying uses
the same exact confirmation phrase. It deletes child records before notebooks,
removes only manifest-owned S3 prefixes, preserves user/auth records, and then
writes the workflow marker.

DSQL/S3 application spans multiple external transactions and has no automatic
rollback in this tool. Do not apply it without an independently approved data
retention/recovery plan and a maintenance window. The runtime
`co_design_app` role must never run this command; use the admin connection only.

## Post-reset checks

1. Start through `sh scripts/start.sh`; `/api/v1/ready` must return 200.
2. Verify the preserved lecturer/admin role and Cognito sign-in.
3. Create a disposable notebook and confirm it begins at Problem identification.
4. Submit deterministic mock turns through all five phases.
5. Confirm student Review, professor Research attribution, human review, access
   audit, and CSV export.
6. Retain backup/quarantine until those checks pass; record approval and reset
   ID outside the repository.
