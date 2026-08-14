"""SQLite schema applied by the local ``StudentStore`` initializer."""

SQLITE_SCHEMA = """
PRAGMA foreign_keys = ON;

CREATE TABLE IF NOT EXISTS users (
    id TEXT PRIMARY KEY,
    identifier TEXT NOT NULL UNIQUE,
    cognito_sub TEXT,
    email TEXT,
    display_name TEXT,
    role TEXT NOT NULL DEFAULT 'student',
    preferences_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT,
    last_login_at TEXT
);

CREATE TABLE IF NOT EXISTS oauth_login_states (
    state TEXT PRIMARY KEY,
    code_verifier TEXT NOT NULL,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS notebooks (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT,
    current_stage TEXT NOT NULL DEFAULT 'problem_identification',
    progress_text TEXT NOT NULL DEFAULT '{}',
    settings_text TEXT NOT NULL DEFAULT '{}',
    conversation_revision INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_notebooks_user_updated
ON notebooks(user_id, updated_at);

CREATE TABLE IF NOT EXISTS messages (
    id TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    is_error INTEGER NOT NULL DEFAULT 0,
    assessment_text TEXT,
    cited_source_ids_text TEXT,
    proposed_stage TEXT,
    decision_status TEXT,
    decision_at TEXT,
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    conversation_revision INTEGER NOT NULL DEFAULT 0,
    previous_message_id TEXT,
    superseded_at_revision INTEGER,
    FOREIGN KEY (notebook_id) REFERENCES notebooks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_messages_notebook_created
ON messages(notebook_id, created_at, id);

CREATE INDEX IF NOT EXISTS idx_messages_notebook_decision
ON messages(notebook_id, decision_status, created_at);

CREATE TABLE IF NOT EXISTS sources (
    id TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    content_type TEXT,
    byte_size INTEGER NOT NULL DEFAULT 0,
    object_key TEXT,
    extracted_text_key TEXT,
    source_url TEXT,
    selected INTEGER NOT NULL DEFAULT 1,
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (notebook_id) REFERENCES notebooks(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_sources_notebook_created
ON sources(notebook_id, created_at, id);

CREATE TABLE IF NOT EXISTS research_observations (
    id TEXT PRIMARY KEY,
    notebook_id TEXT NOT NULL,
    user_message_id TEXT NOT NULL,
    assistant_message_id TEXT NOT NULL UNIQUE,
    conversation_revision INTEGER NOT NULL DEFAULT 0,
    coding_status TEXT NOT NULL,
    coding_version TEXT NOT NULL,
    prompt_version TEXT NOT NULL,
    provider TEXT NOT NULL,
    model_id TEXT NOT NULL,
    coaching_profile TEXT NOT NULL,
    phase_id TEXT NOT NULL,
    dominant_clear TEXT,
    facione_behaviors_text TEXT NOT NULL DEFAULT '[]',
    ethics_concepts_text TEXT NOT NULL DEFAULT '[]',
    evidence_text TEXT NOT NULL DEFAULT '[]',
    holistic_candidate_text TEXT,
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (notebook_id) REFERENCES notebooks(id) ON DELETE CASCADE,
    FOREIGN KEY (user_message_id) REFERENCES messages(id) ON DELETE CASCADE,
    FOREIGN KEY (assistant_message_id) REFERENCES messages(id) ON DELETE CASCADE
);

CREATE INDEX IF NOT EXISTS idx_research_observations_notebook_created
ON research_observations(notebook_id, created_at, id);

CREATE INDEX IF NOT EXISTS idx_research_observations_status_created
ON research_observations(coding_status, created_at, id);

CREATE TABLE IF NOT EXISTS research_reviews (
    id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL,
    reviewer_user_id TEXT NOT NULL,
    status TEXT NOT NULL,
    coding_status TEXT,
    dominant_clear TEXT,
    facione_behaviors_text TEXT,
    ethics_concepts_text TEXT,
    evidence_text TEXT,
    holistic_candidate_text TEXT,
    notes TEXT,
    supersedes_review_id TEXT,
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (observation_id) REFERENCES research_observations(id) ON DELETE CASCADE,
    FOREIGN KEY (reviewer_user_id) REFERENCES users(id),
    FOREIGN KEY (supersedes_review_id) REFERENCES research_reviews(id)
);

CREATE INDEX IF NOT EXISTS idx_research_reviews_observation_created
ON research_reviews(observation_id, created_at, id);

CREATE TABLE IF NOT EXISTS research_adjudications (
    id TEXT PRIMARY KEY,
    observation_id TEXT NOT NULL,
    adjudicator_user_id TEXT NOT NULL,
    decision TEXT NOT NULL,
    coding_status TEXT,
    dominant_clear TEXT,
    facione_behaviors_text TEXT,
    ethics_concepts_text TEXT,
    evidence_text TEXT,
    holistic_candidate_text TEXT,
    notes TEXT,
    supersedes_adjudication_id TEXT,
    referenced_review_ids_text TEXT NOT NULL DEFAULT '[]',
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (observation_id) REFERENCES research_observations(id) ON DELETE CASCADE,
    FOREIGN KEY (adjudicator_user_id) REFERENCES users(id),
    FOREIGN KEY (supersedes_adjudication_id) REFERENCES research_adjudications(id)
);

CREATE INDEX IF NOT EXISTS idx_research_adjudications_observation_created
ON research_adjudications(observation_id, created_at, id);

CREATE TABLE IF NOT EXISTS research_access_events (
    id TEXT PRIMARY KEY,
    actor_user_id TEXT NOT NULL,
    action TEXT NOT NULL,
    scope TEXT NOT NULL,
    request_id TEXT NOT NULL,
    target_user_id TEXT,
    target_count INTEGER,
    notebook_id TEXT,
    observation_id TEXT,
    filters_text TEXT NOT NULL DEFAULT '{}',
    metadata_text TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_research_access_actor_created
ON research_access_events(actor_user_id, created_at, id);

CREATE INDEX IF NOT EXISTS idx_research_access_request
ON research_access_events(request_id, created_at, id);

CREATE TABLE IF NOT EXISTS system_metadata (
    key TEXT PRIMARY KEY,
    value_text TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

# Child rows deleted explicitly when a notebook is removed (DSQL has no FK
# cascade). Reviews and adjudications are linked indirectly through an
# observation, so a flat ``WHERE notebook_id`` loop is not correct.
NOTEBOOK_CHILD_DELETE_PLAN = (
    (
        "research_adjudications",
        "observation_id IN (SELECT id FROM research_observations WHERE notebook_id = ?)",
    ),
    (
        "research_reviews",
        "observation_id IN (SELECT id FROM research_observations WHERE notebook_id = ?)",
    ),
    ("research_access_events", "notebook_id = ?"),
    ("research_observations", "notebook_id = ?"),
    ("messages", "notebook_id = ?"),
    ("sources", "notebook_id = ?"),
)

# Backwards-compatible inventory for schema/admin tooling. Runtime deletion
# must use NOTEBOOK_CHILD_DELETE_PLAN because predicates differ by table.
NOTEBOOK_CHILD_TABLES = tuple(
    table for table, _predicate in NOTEBOOK_CHILD_DELETE_PLAN
)

