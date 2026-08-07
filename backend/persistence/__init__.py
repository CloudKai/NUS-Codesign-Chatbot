"""Storage ports and provider selection for local and AWS production runtimes.

Application code should obtain stores and file storage through the factory
helpers rather than constructing SQLite or filesystem paths directly when the
active provider may be DSQL or S3.
"""

from __future__ import annotations

from .factory import create_file_storage, create_student_store, get_file_storage
from .ports import FileStorage, StoredObject

__all__ = [
    "FileStorage",
    "StoredObject",
    "create_file_storage",
    "create_student_store",
    "get_file_storage",
]
