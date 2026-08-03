"""
Storage abstraction for per-student, per-project state and history.

LocalJSONStorage: zero AWS setup, works instantly, good for local testing and the first demo.
CAVEAT: on Lambda, /tmp is ephemeral per-instance -- fine for a live single-session demo,
but state can vanish on cold start / concurrent instances. Swap to DynamoDBStorage
(stubbed below) once the core loop is validated -- same interface, ~30 min to wire up.
"""

import json
import os
import tempfile
import threading

_LOCK = threading.Lock()
_STORE_PATH = os.environ.get(
    "STORE_PATH",
    os.path.join(tempfile.gettempdir(), "poc_store.json"),
)

os.makedirs(os.path.dirname(_STORE_PATH), exist_ok=True)


class LocalJSONStorage:
    def _read_all(self):
        if not os.path.exists(_STORE_PATH):
            return {}
        with open(_STORE_PATH, "r") as f:
            return json.load(f)

    def _write_all(self, data):
        os.makedirs(os.path.dirname(_STORE_PATH), exist_ok=True)
        with open(_STORE_PATH, "w") as f:
            json.dump(data, f, indent=2)

    def _key(self, student_id, project_id):
        return f"{student_id}::{project_id}"

    def get_state(self, student_id: str, project_id: str) -> dict:
        with _LOCK:
            data = self._read_all()
            key = self._key(student_id, project_id)
            return data.get(key, {"phase": "empathize", "turn_count": 0, "history": []})

    def save_turn(self, student_id: str, project_id: str, phase: str, user_msg: str, assistant_msg: str) -> dict:
        with _LOCK:
            data = self._read_all()
            key = self._key(student_id, project_id)
            state = data.get(key, {"phase": phase, "turn_count": 0, "history": []})
            state["phase"] = phase
            state["turn_count"] = state.get("turn_count", 0) + 1
            state["history"].append({"role": "user", "content": user_msg})
            state["history"].append({"role": "assistant", "content": assistant_msg})
            data[key] = state
            self._write_all(data)
            return state


# --- DynamoDB variant (uncomment and wire up when ready to deploy for real) ---
#
# import boto3
# TABLE_NAME = os.environ.get("TABLE_NAME", "poc_project_state")
#
# class DynamoDBStorage:
#     def __init__(self):
#         self.table = boto3.resource("dynamodb").Table(TABLE_NAME)
#
#     def get_state(self, student_id, project_id):
#         resp = self.table.get_item(Key={"pk": f"{student_id}#{project_id}"})
#         return resp.get("Item", {"phase": "empathize", "turn_count": 0, "history": []})
#
#     def save_turn(self, student_id, project_id, phase, user_msg, assistant_msg):
#         state = self.get_state(student_id, project_id)
#         state["phase"] = phase
#         state["turn_count"] = state.get("turn_count", 0) + 1
#         state["history"] = state.get("history", []) + [
#             {"role": "user", "content": user_msg},
#             {"role": "assistant", "content": assistant_msg},
#         ]
#         self.table.put_item(Item={"pk": f"{student_id}#{project_id}", **state})
#         return state