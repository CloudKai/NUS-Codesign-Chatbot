"""Aurora DSQL administration helpers used by the bootstrap CLI."""

from scripts.dsql.cli import (
    REVISION_NULL_BACKFILL_BATCH_SIZE,
    apply_dsql_schema,
    apply_missing_message_revision_columns,
    apply_missing_revision_columns,
    apply_revision_null_backfills,
    build_revision_null_backfill_update,
    column_default_is_zero,
    fetch_null_conversation_revision_ids,
    fetch_table_column_details,
    fetch_table_columns,
    is_async_index_ddl,
    main,
    plan_missing_message_revision_statements,
    plan_missing_notebooks_conversation_revision_statements,
    wait_for_async_index_job,
)

__all__ = [
    "REVISION_NULL_BACKFILL_BATCH_SIZE",
    "apply_dsql_schema",
    "apply_missing_message_revision_columns",
    "apply_missing_revision_columns",
    "apply_revision_null_backfills",
    "build_revision_null_backfill_update",
    "column_default_is_zero",
    "fetch_null_conversation_revision_ids",
    "fetch_table_column_details",
    "fetch_table_columns",
    "is_async_index_ddl",
    "main",
    "plan_missing_message_revision_statements",
    "plan_missing_notebooks_conversation_revision_statements",
    "wait_for_async_index_job",
]
