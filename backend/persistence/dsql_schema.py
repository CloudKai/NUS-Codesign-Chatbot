"""Aurora DSQL schema for structured application state.

Differences from the SQLite schema in ``student_store.SCHEMA``:

- No FOREIGN KEY constraints (unsupported in Aurora DSQL; enforce in app code).
- No ON DELETE CASCADE (delete child rows explicitly in the store).
- JSON-shaped fields remain TEXT (DSQL does not use JSON/JSONB columns here).
- UUID primary keys stay application-generated TEXT ids.
- Partial unique index on ``users(cognitoSub)`` is created when supported.

Do not auto-create or destroy DSQL clusters from application startup. Schema
application is explicit via store initialization or ``scripts/init_db.py``.
"""

from __future__ import annotations

DSQL_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    identifier TEXT NOT NULL UNIQUE,
    metadata TEXT NOT NULL DEFAULT '{}',
    createdAt TEXT NOT NULL,
    cognitoSub TEXT,
    email TEXT,
    displayName TEXT,
    role TEXT NOT NULL DEFAULT 'student',
    updatedAt TEXT,
    lastLoginAt TEXT
);

CREATE TABLE IF NOT EXISTS threads (
    id TEXT PRIMARY KEY,
    createdAt TEXT NOT NULL,
    name TEXT,
    userId TEXT,
    userIdentifier TEXT,
    tags TEXT NOT NULL DEFAULT '[]',
    metadata TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS steps (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,
    threadId TEXT NOT NULL,
    parentId TEXT,
    streaming INTEGER NOT NULL DEFAULT 0,
    waitForAnswer INTEGER,
    isError INTEGER,
    metadata TEXT NOT NULL DEFAULT '{}',
    tags TEXT NOT NULL DEFAULT '[]',
    input TEXT,
    output TEXT,
    createdAt TEXT,
    command TEXT,
    start TEXT,
    end TEXT,
    generation TEXT NOT NULL DEFAULT '{}',
    showInput TEXT,
    language TEXT,
    indent INTEGER,
    defaultOpen INTEGER,
    modes TEXT NOT NULL DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_steps_thread_created ON steps(threadId, createdAt);

CREATE TABLE IF NOT EXISTS folders (
    id TEXT PRIMARY KEY,
    ownerId TEXT NOT NULL,
    name TEXT NOT NULL,
    color TEXT NOT NULL DEFAULT '#6d5dfc',
    position INTEGER NOT NULL DEFAULT 0,
    createdAt TEXT NOT NULL,
    updatedAt TEXT NOT NULL,
    UNIQUE(ownerId, name)
);

CREATE TABLE IF NOT EXISTS thread_folders (
    threadId TEXT PRIMARY KEY,
    folderId TEXT NOT NULL,
    ownerId TEXT NOT NULL,
    createdAt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS feedbacks (
    id TEXT PRIMARY KEY,
    forId TEXT NOT NULL UNIQUE,
    threadId TEXT NOT NULL,
    value INTEGER NOT NULL,
    comment TEXT
);

CREATE TABLE IF NOT EXISTS model_turns (
    id TEXT PRIMARY KEY,
    threadId TEXT NOT NULL,
    userMessageId TEXT,
    assistantMessageId TEXT,
    modelId TEXT NOT NULL,
    reasoningEffort TEXT,
    usage TEXT NOT NULL DEFAULT '{}',
    createdAt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS openai_thread_state (
    threadId TEXT PRIMARY KEY,
    previousResponseId TEXT,
    modelId TEXT,
    history TEXT NOT NULL DEFAULT '[]',
    vectorStoreId TEXT,
    sourceSnapshot TEXT NOT NULL DEFAULT '[]',
    groundingMode TEXT NOT NULL DEFAULT 'source_first',
    updatedAt TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notebook_sources (
    id TEXT PRIMARY KEY,
    threadId TEXT NOT NULL,
    ownerId TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    mime TEXT NOT NULL DEFAULT 'text/plain',
    path TEXT,
    sourceUrl TEXT,
    extractedText TEXT NOT NULL DEFAULT '',
    size INTEGER NOT NULL DEFAULT 0,
    selected INTEGER NOT NULL DEFAULT 1,
    metadata TEXT NOT NULL DEFAULT '{}',
    createdAt TEXT NOT NULL,
    updatedAt TEXT NOT NULL,
    objectKey TEXT,
    contentType TEXT,
    fileSize INTEGER,
    uploadedAt TEXT
);

CREATE INDEX IF NOT EXISTS idx_notebook_sources_thread
ON notebook_sources(threadId, createdAt);

CREATE TABLE IF NOT EXISTS phase_transitions (
    id TEXT PRIMARY KEY,
    threadId TEXT NOT NULL,
    fromStage TEXT NOT NULL,
    toStage TEXT NOT NULL,
    assessment TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    createdAt TEXT NOT NULL,
    resolvedAt TEXT
);

CREATE INDEX IF NOT EXISTS idx_phase_transitions_thread_status
ON phase_transitions(threadId, status, createdAt);

CREATE TABLE IF NOT EXISTS app_sessions (
    id TEXT PRIMARY KEY,
    tokenHash TEXT NOT NULL UNIQUE,
    userId TEXT NOT NULL,
    createdAt TEXT NOT NULL,
    expiresAt TEXT NOT NULL,
    lastSeenAt TEXT,
    revokedAt TEXT
);

CREATE INDEX IF NOT EXISTS idx_app_sessions_token_hash
ON app_sessions(tokenHash);

CREATE INDEX IF NOT EXISTS idx_app_sessions_user
ON app_sessions(userId);

CREATE TABLE IF NOT EXISTS oauth_login_states (
    state TEXT PRIMARY KEY,
    codeVerifier TEXT NOT NULL,
    createdAt TEXT NOT NULL,
    expiresAt TEXT NOT NULL
);
"""


# Child tables deleted explicitly when a thread is removed (no FK cascade).
THREAD_CHILD_TABLES = (
    "steps",
    "feedbacks",
    "model_turns",
    "openai_thread_state",
    "notebook_sources",
    "phase_transitions",
    "thread_folders",
)
