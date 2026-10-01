# Database and persistence

## Logical model

SQLite and Aurora DSQL implement the same five-table application model:

```text
users
  ├── notebooks
  │     ├── messages
  │     └── sources
  └── preferences_text

oauth_login_states           pre-authentication, one-time state/PKCE data
```

| Table | Responsibility |
|---|---|
| `users` | Stable application identity, Cognito subject, profile, role, preferences |
| `oauth_login_states` | Expiring one-time OAuth state and PKCE verifier; never session tokens |
| `notebooks` | Owner-scoped conversation root, settings, learning metadata, active conversation revision |
| `messages` | Active/historical turns, assessments, transition decisions, source snapshots, internal idempotency reservations |
| `sources` | Notebook-scoped source metadata, selection, extracted text/object references |

There is no application-session or standalone phase-transition table. Cognito
owns browser authentication. Pending/resolved transition records and durable
coach-idempotency reservations use structured internal message rows that normal
history/count queries filter out.

## System of record

SQLite locally and Aurora DSQL in production are the **only** durable chat
transcript. Do not store student messages in:

- AgentCore Runtime session memory (in-process LRU, lost on cold start)
- AgentCore Memory strategies (semantic / summarization)
- DynamoDB
- a JSON file such as the POC ``poc_store.json``

Each AgentCore invoke is transcript-stateless: FastAPI sends bounded canonical
history and persists the turn in ``messages`` after structured validation.
With affinity disabled, each invoke uses a fresh ``runtimeSessionId``; optional
FastAPI-owned affinity may reuse an opaque compute id that is never a notebook
id. Student ``transcript.txt`` download is a projection of ``get_messages``,
not a second store.

## Ownership and relationships

Ownership is derived, not copied onto every child row:

```text
messages.notebook_id -> notebooks.user_id -> users.id
sources.notebook_id  -> notebooks.user_id -> users.id
```

SQLite enforces declared foreign keys. Aurora DSQL does not provide the same
foreign-key/cascade behavior, so application transactions validate ownership
and delete children in an explicit order. Never trust a client-supplied user ID
or raw storage path.

Source objects use generated owner/notebook/source prefixes. Raw uploads and
derived extracted text use separate namespaces. Database deletion commits
before retryable object-prefix cleanup; a repeated owner-scoped delete can
finish cleanup safely.

## Conversation revisions and idempotency

User-message Edit creates an append-only conversation revision. It does not
rewrite or truncate historical message content.

- `notebooks.conversation_revision` identifies the active branch.
- `messages.conversation_revision` records the branch on which a row was added.
- `previous_message_id` records replacement lineage.
- `superseded_at_revision` removes a row from later active projections without
  deleting it.
- revision compare-and-swap prevents a stale worker from committing.

Coach requests reserve an owner/notebook-scoped idempotency key with a request
fingerprint and lease. Exact completed retries replay the persisted `CoachTurn`;
changed-payload reuse conflicts; expired/stale workers cannot commit after a
new worker acquires the lease.

## Transaction boundaries

The important atomic units are:

- coaching user row + assistant row + assessment + pending/automatic
  transition + notebook metadata;
- transition acceptance plus journey metadata update;
- append-only revise branch creation plus replacement turn;
- idempotency lease verification plus turn persistence;
- owner/profile reconciliation and SQLite compatibility repair.

Provider and S3 network work must not occur inside a retryable DSQL OCC callback
when a retry could repeat the external side effect. SQLSTATE `40001` retries the
whole database unit with a bounded policy.

## SQLite lifecycle and compatibility

Opening `StudentStore` ensures the current schema and performs known additive,
idempotent compatibility migrations. Tests cover legacy camelCase users/OAuth
state, legacy workspace copies, split Cognito owners, foreign-key repair, and
conversation-revision columns.

The public `StudentStore` remains stable while implementation is incrementally
split under `backend.persistence.store`: shared contracts and JSON helpers,
SQLite schema text, compatibility migrations, and bound source operations.
`DsqlStudentStore` binds the same operation objects even though it intentionally
does not call the SQLite constructor. Existing `_connect`, lock, serialization,
metadata-splitting, revision-SQL and idempotency-marker compatibility seams are
retained until their consumers can move behind explicit repository contracts.

These automatic compatibility steps are not permission to reset data. Before a
new migration:

1. inspect the existing database and Git state;
2. back up the SQLite file and associated source objects;
3. add a synthetic legacy-schema regression fixture;
4. make the migration additive and rerunnable;
5. prove IDs, owners, messages, sources, learning state, and extracted text
   survive;
6. document rollback without destructive `DROP`/recreate operations.

`scripts/init_db.py` is an explicit initialization helper. It refuses an
existing database unless `--force` is deliberately supplied. Normal validation
must not invoke it against developer data.

## Aurora DSQL lifecycle

Application startup never performs DDL. `scripts/init_dsql.py` is the stable
admin-only entrypoint; planning, catalog inspection, bounded backfill and
execution live in `scripts.dsql.cli`. It uses DbConnectAdmin. Runtime uses
`co_design_app` with
DbConnect and object-level SELECT/INSERT/UPDATE/DELETE grants only.

DSQL migrations must account for:

- one DDL statement per transaction;
- asynchronous index jobs;
- catalog inspection before additive ALTERs;
- bounded NULL backfill batches;
- OCC serialization failures;
- no assumption of PostgreSQL foreign keys, cascades, or unrestricted DDL.

The deterministic suite verifies SQL adaptation and transaction policy with
fakes/proxies. It does not prove wire-level Aurora behavior. Live DSQL writes
require explicit approval, the guarded smoke command, disposable records, and
cleanup in `finally`.

## Query and index review

Important query shapes are owner lookup, notebook activity ordering, active
branch message history, pending transition lookup, selected notebook sources,
and source activity ordering. DSQL bootstrap creates explicit asynchronous
indexes for these paths. When adding a query, verify both adapters, ownership
scope, deterministic ordering, and whether the index exists before claiming
production scalability.

## Schema-change checklist

- No destructive migration or user-data reset.
- SQLite and DSQL semantics remain aligned.
- Fresh schema and legacy upgrade are both tested.
- Migration is idempotent and interruption-safe.
- Backup and rollback are documented.
- Runtime DSQL role cannot execute DDL.
- API/persistence contracts remain backward-compatible.
- No secret, token, private path, or source content enters logs.
