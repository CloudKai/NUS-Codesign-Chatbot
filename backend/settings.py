from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv


PROJECT_ROOT = Path(__file__).resolve().parents[1]
load_dotenv(PROJECT_ROOT / ".env")


def _boolean(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


def _project_path(name: str, default: str) -> Path:
    """Resolve a configured path relative to the project when it is not absolute."""
    configured = Path(os.getenv(name, default)).expanduser()
    return (configured if configured.is_absolute() else PROJECT_ROOT / configured).resolve()


@dataclass
class Settings:
    project_root: Path = PROJECT_ROOT
    data_dir: Path = Path(os.getenv("APP_DATA_DIR", PROJECT_ROOT / "data")).resolve()
    database_path: Path = Path(
        os.getenv("APP_DATABASE_PATH", PROJECT_ROOT / "data" / "co_design.sqlite3")
    ).resolve()
    files_dir: Path = Path(
        os.getenv("APP_FILES_DIR", PROJECT_ROOT / "data" / "files")
    ).resolve()
    workspaces_dir: Path = Path(
        os.getenv("APP_WORKSPACES_DIR", PROJECT_ROOT / "data" / "workspaces")
    ).resolve()
    lecture_notes_dir: Path = _project_path("LECTURE_NOTES_DIR", "lecture_notes")
    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    enable_local_code_execution: bool = _boolean("ENABLE_LOCAL_CODE_EXECUTION", False)
    mock_openai: bool = _boolean("MOCK_OPENAI", False)
    mock_recommend_advance: bool = _boolean("MOCK_RECOMMEND_ADVANCE", False)
    auto_advance_stages: bool = _boolean("AUTO_ADVANCE_STAGES", False)
    model_provider: str = os.getenv("MODEL_PROVIDER", "mock").strip().lower()
    ollama_base_url: str = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")
    ollama_chat_model: str = os.getenv("OLLAMA_CHAT_MODEL", "gpt-oss:20b")
    ollama_embedding_model: str = os.getenv("OLLAMA_EMBEDDING_MODEL", "nomic-embed-text")
    openai_chat_model: str = os.getenv("OPENAI_CHAT_MODEL", "gpt-5.6-luna")
    api_base_url: str = os.getenv("CO_DESIGN_API_URL", "http://127.0.0.1:8000")
    use_local_api: bool = _boolean("USE_LOCAL_API", False)
    max_tool_iterations: int = int(os.getenv("MAX_TOOL_ITERATIONS", "20"))
    max_files: int = int(os.getenv("MAX_FILES_PER_MESSAGE", "10"))
    max_lecture_notes: int = int(os.getenv("MAX_LECTURE_NOTES", "50"))
    max_course_material_size_mb: int = int(
        os.getenv("MAX_COURSE_MATERIAL_SIZE_MB", "50")
    )
    max_file_size_mb: int = int(os.getenv("MAX_FILE_SIZE_MB", "25"))
    python_timeout_seconds: int = int(os.getenv("PYTHON_TIMEOUT_SECONDS", "30"))
    default_model: str = os.getenv("DEFAULT_CHAT_MODEL", "gpt-5.6-luna")
    default_reasoning_effort: str = os.getenv("DEFAULT_REASONING_EFFORT", "low")
    image_model: str = os.getenv("IMAGE_MODEL", "gpt-image-2")

    def ensure_directories(self) -> None:
        for directory in (
            self.data_dir,
            self.files_dir,
            self.workspaces_dir,
            self.lecture_notes_dir,
        ):
            directory.mkdir(parents=True, exist_ok=True)


settings = Settings()
settings.ensure_directories()
