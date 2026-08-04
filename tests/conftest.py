import os
import tempfile
from pathlib import Path


TEST_ROOT = Path(tempfile.mkdtemp(prefix="co-design-tests-"))
os.environ["MOCK_OPENAI"] = "true"
os.environ["MODEL_PROVIDER"] = "mock"
# AppTest covers the legacy Streamlit chat path; Learning Path API is exercised
# separately in API/workflow tests and live demo startup scripts.
os.environ["USE_LOCAL_API"] = "false"
os.environ["AUTO_ADVANCE_STAGES"] = "false"
os.environ["DEFAULT_CHAT_MODEL"] = "gpt-5.6-luna"
os.environ["OPENAI_CHAT_MODEL"] = "gpt-5.6-luna"
os.environ["DEFAULT_REASONING_EFFORT"] = "low"
os.environ["APP_DATA_DIR"] = str(TEST_ROOT)
os.environ["APP_DATABASE_PATH"] = str(TEST_ROOT / "co_design.sqlite3")
os.environ["APP_FILES_DIR"] = str(TEST_ROOT / "files")
os.environ["APP_WORKSPACES_DIR"] = str(TEST_ROOT / "workspaces")
os.environ["LECTURE_NOTES_DIR"] = str(TEST_ROOT / "lecture_notes")
