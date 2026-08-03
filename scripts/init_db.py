import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.student_store import StudentStore


if __name__ == "__main__":
    store = StudentStore()
    print(f"Initialized Co-design student database at {store.path}")
