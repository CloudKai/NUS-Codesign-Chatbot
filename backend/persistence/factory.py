"""Configuration-driven factories for database and file-storage providers."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

from backend.settings import settings

from .local_files import LocalFileStorage
from .memory_files import MemoryFileStorage
from .ports import FileStorage
from .s3_files import S3FileStorage


def create_file_storage(
    *,
    provider: str | None = None,
    root: Path | None = None,
    s3_client: Any | None = None,
) -> FileStorage:
    """Return a FileStorage implementation for the configured provider.

    Args:
        provider: Override ``FILE_STORAGE_PROVIDER`` (``local``, ``s3``, ``memory``).
        root: Local root directory when provider is ``local``.
        s3_client: Optional injected boto3 client for tests.

    Raises:
        ValueError: when production S3 configuration is incomplete or the
            provider name is unknown.
    """
    selected = (provider or settings.file_storage_provider).strip().lower()
    if selected == "local":
        return LocalFileStorage(root or settings.files_dir)
    if selected == "memory":
        return MemoryFileStorage()
    if selected == "s3":
        return S3FileStorage(
            bucket=settings.user_uploads_bucket,
            region=settings.aws_region,
            client=s3_client,
        )
    raise ValueError(f"Unsupported FILE_STORAGE_PROVIDER: {selected}")


@lru_cache(maxsize=1)
def get_file_storage() -> FileStorage:
    """Return the process-wide FileStorage singleton for the active provider."""
    return create_file_storage()


def reset_file_storage_cache() -> None:
    """Clear the FileStorage singleton (used by tests)."""
    get_file_storage.cache_clear()


def create_student_store(
    path: Path | None = None,
    identifier: str = "local-student",
    **kwargs: Any,
):
    """Return a StudentStore for the configured database provider.

    An explicit *path* always selects the SQLite ``StudentStore`` so local tests
    and ``scripts/init_db.py`` keep working. Production DSQL is selected only
    when ``DATABASE_PROVIDER=dsql`` and no path is supplied.

    Returns:
        ``StudentStore`` or ``DsqlStudentStore`` instance.
    """
    from backend.student_store import StudentStore

    provider = settings.database_provider
    if path is not None or provider == "sqlite":
        return StudentStore(path=path, identifier=identifier, **kwargs)
    if provider == "dsql":
        from .dsql_student_store import DsqlStudentStore

        return DsqlStudentStore(identifier=identifier, **kwargs)
    raise ValueError(f"Unsupported DATABASE_PROVIDER: {provider}")


def validate_storage_configuration() -> None:
    """Raise ``ValueError`` when production storage settings are incomplete.

    Safe to call at API startup. Does not contact AWS or open connections.
    Rejects ``DSQL_USER=admin`` for runtime (admin is migration-only).
    """
    if settings.database_provider == "dsql":
        if not settings.dsql_endpoint.strip():
            raise ValueError(
                "DATABASE_PROVIDER=dsql requires DSQL_ENDPOINT to be configured"
            )
        if not settings.aws_region.strip():
            raise ValueError(
                "DATABASE_PROVIDER=dsql requires AWS_REGION to be configured"
            )
        role = settings.dsql_user.strip()
        if not role:
            raise ValueError(
                "DATABASE_PROVIDER=dsql requires DSQL_USER "
                "(runtime role co_design_app)"
            )
        if role.lower() == "admin":
            raise ValueError(
                "DSQL_USER=admin is not allowed for application runtime; "
                "use co_design_app (admin is for scripts/init_dsql.py only)"
            )
    elif settings.database_provider != "sqlite":
        raise ValueError(
            f"Unsupported DATABASE_PROVIDER: {settings.database_provider}"
        )

    if settings.file_storage_provider == "s3":
        if not settings.user_uploads_bucket.strip():
            raise ValueError(
                "FILE_STORAGE_PROVIDER=s3 requires USER_UPLOADS_BUCKET"
            )
        if not settings.aws_region.strip():
            raise ValueError(
                "FILE_STORAGE_PROVIDER=s3 requires AWS_REGION"
            )
    elif settings.file_storage_provider not in {"local", "memory"}:
        raise ValueError(
            f"Unsupported FILE_STORAGE_PROVIDER: {settings.file_storage_provider}"
        )
