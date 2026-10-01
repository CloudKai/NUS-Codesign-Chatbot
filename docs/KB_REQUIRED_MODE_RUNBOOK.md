# Managed Knowledge Base `required`-mode deployment runbook

**Documentation only.** No command in this file has been executed in this
change set. Nothing here uploads to S3, starts a Knowledge Base sync, or
calls Bedrock Retrieve. Live AWS steps stay behind explicit operator flags
(`--confirm`, `--i-approve-live-bedrock`).

`required` (fail closed) is the intended production filter mode. Do not
switch to `degraded_unfiltered` as a fix. Do not enable `required` on a
live environment until this checklist has actually passed on that
environment.

Until sidecars are ingested, keep the live env on:

```text
KNOWLEDGE_BASE_METADATA_FILTER_MODE=degraded_unfiltered
```

Only set `KNOWLEDGE_BASE_METADATA_FILTER_MODE=required` after step 9.

## Environment variables

| Name | Role |
|---|---|
| `COURSE_MATERIALS_BUCKET` | Shared course S3 bucket (required in production when a Knowledge Base is configured) |
| `COURSE_MATERIALS_PREFIX` | Shared prefix; production uses `course/` |
| `AWS_REGION` / `KNOWLEDGE_BASE_REGION` | Region for S3 and Retrieve |
| `KNOWLEDGE_BASE_ID` | Bedrock Knowledge Base id (production `JUQNP8AZAZ`) |
| `KNOWLEDGE_BASE_TYPE` | `MANAGED` for `JUQNP8AZAZ` |
| `KNOWLEDGE_BASE_DATA_SOURCE_ID` | Operator-only CLI variable for `StartIngestionJob`. **Not** read by the app. |
| `KNOWLEDGE_BASE_METADATA_FILTER_MODE` | `required` after this checklist; `degraded_unfiltered` until then |
| `KNOWLEDGE_BASE_STRICT_METADATA_FILTER` | Legacy; `true` still maps to `required`. `false` does **not** skip the filter. |

Use `.venv/bin/python` from the repository root. `PYTHONPATH` must include
the repo root (the scripts import `backend.*`).

## 1. Generate sidecars (local / dry-run)

Lists planned `course_material_id` sidecar keys. Does not write S3.

```sh
PYTHONPATH=. .venv/bin/python scripts/sync_course_kb_metadata.py
```

Optional: write sibling `.metadata.json` files next to local lecture copies
(still no S3):

```sh
PYTHONPATH=. .venv/bin/python scripts/sync_course_kb_metadata.py --write-local
```

## 2. Upload sidecars (live S3; requires `--confirm`)

```sh
PYTHONPATH=. .venv/bin/python scripts/sync_course_kb_metadata.py --confirm
```

`--confirm` is required. The script never writes under `users/`.

## 3. Sync the Knowledge Base data source (live AWS)

The application does not start ingestion. Use the AWS CLI with operator
credentials. Substitute the live data-source id; do not invent one.

```sh
aws bedrock-agent start-ingestion-job \
  --knowledge-base-id "$KNOWLEDGE_BASE_ID" \
  --data-source-id "$KNOWLEDGE_BASE_DATA_SOURCE_ID" \
  --region "${KNOWLEDGE_BASE_REGION:-$AWS_REGION}"
```

## 4. Wait for sync success (live AWS)

```sh
aws bedrock-agent get-ingestion-job \
  --knowledge-base-id "$KNOWLEDGE_BASE_ID" \
  --data-source-id "$KNOWLEDGE_BASE_DATA_SOURCE_ID" \
  --ingestion-job-id "<id-from-start>" \
  --region "${KNOWLEDGE_BASE_REGION:-$AWS_REGION}"
```

Proceed only when `status` is `COMPLETE` and statistics show documents
indexed. `FAILED` / `STOPPED` is a stop.

## 5. Run metadata verification (local; no AWS)

Answers: does each course document have a sidecar, and does
`course_material_id` match `course_material_id_from_object_key`?

```sh
PYTHONPATH=. .venv/bin/python scripts/diagnostics/check_course_kb_metadata.py
```

`--i-approve-live-bedrock` is refused here. Ingestion completion and filtered
Retrieve are **not executed** by this script; they are the AWS CLI steps
above plus the Retrieve diagnostics below.

Exit `0` only when every local course file has a matching canonical sidecar.

## 6. Dry-run the production filter (local; no AWS)

Prints the settings-derived mode (must match production) and the filter that
would be sent. Does not call Bedrock.

```sh
PYTHONPATH=. .venv/bin/python scripts/diagnostics/check_knowledge_base_retrieve.py --dry-run
```

Confirm stderr contains `metadata_filter_mode=required (production-equivalent)`
(or whatever the live env is actually set to) and that JSON
`filter_preview.kind` is `equals` for one source.

## 7. Test one `equals` filter (live Retrieve; requires approval)

One source → `equals` on `course_material_id`. Uses the same adapter and
the same settings-derived mode as production. There is no unfiltered retry.

```sh
PYTHONPATH=. .venv/bin/python scripts/diagnostics/check_knowledge_base_retrieve.py \
  --i-approve-live-bedrock \
  --max-requests 1 \
  --query "week 1 introduction innovation" \
  --source "Week 1 Introduction to innovation v3.pdf"
```

Pass only when `ok` is true, `fallback_occurred` is false,
`retrieve_call_count` is 1, and a validated hit maps to that object key.

Equivalent Week 1 probe:

```sh
PYTHONPATH=. .venv/bin/python scripts/diagnostics/test_course_retrieval.py \
  --dry-run
PYTHONPATH=. .venv/bin/python scripts/diagnostics/test_course_retrieval.py \
  --i-approve-live-bedrock \
  --query "what are the week 1 contents talking about?" \
  --source "Week 1 Introduction to innovation v3.pdf"
```

`--dry-run` does not need `--i-approve-live-bedrock`. Live does.

## 8. Test one multi-source `in` filter (live Retrieve; requires approval)

Two sources → `in` on `course_material_id`. Dry-run first:

```sh
PYTHONPATH=. .venv/bin/python scripts/diagnostics/check_knowledge_base_retrieve.py \
  --dry-run \
  --source "Week 1 Introduction to innovation v3.pdf" \
  --second-source "readings/week1.pdf"
```

Confirm `filter_preview.kind` is `in`. Then:

```sh
PYTHONPATH=. .venv/bin/python scripts/diagnostics/check_knowledge_base_retrieve.py \
  --i-approve-live-bedrock \
  --max-requests 1 \
  --query "week 1 introduction innovation" \
  --source "Week 1 Introduction to innovation v3.pdf" \
  --second-source "readings/week1.pdf"
```

Replace `--second-source` with a real second course object that exists in
the catalog. Pass only when validated hits are limited to the selected keys
and `fallback_occurred` is false.

## 9. Only then set production filter mode to `required`

```text
KNOWLEDGE_BASE_METADATA_FILTER_MODE=required
```

Restart the app so settings reload. A metadata-filter `ValidationException`
is an evidence gap. The adapter **never** retries unfiltered.

Do not treat an unfiltered Retrieve as proof that filtered mode is live.

## Fail-closed behaviour (already in code; do not weaken)

- `required` sends `equals` (one id) or `in` (many ids).
- `ValidationException` → `unavailable` / `validation_error`. No second call.
- Empty `COURSE_MATERIALS_BUCKET` with a configured Knowledge Base fails
  production startup (`validate_knowledge_base_bucket_binding`).
- Retrieve hits whose bucket cannot be positively confirmed are dropped.
