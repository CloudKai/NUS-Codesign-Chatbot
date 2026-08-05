"""
CDE2300 Socratic Design Thinking POC -- minimal single-file backend.

This is the API only. The student-facing UI is streamlit_app.py.

Run locally:
    pip install -r requirements.txt
    uvicorn main:app --reload --port 8000
    streamlit run streamlit_app.py   # in a second terminal

Deploy to Lambda (fastest real-AWS path):
    See README_1.md -- zip this folder + deps, upload, enable Function URL.
    (Lambda hosts the API; run Streamlit separately, e.g. Streamlit Community
    Cloud, pointed at the Function URL via BACKEND_URL.)
"""

import base64
import os
from pathlib import Path

from dotenv import load_dotenv
import boto3
from fastapi import FastAPI
from pydantic import BaseModel

from phases import build_system_prompt, CRITIQUE_EVERY_N_TURNS
from storage import LocalJSONStorage

# .env lives outside the repo by default (e.g. so it's never at risk of being
# committed). Override with ENV_FILE if you keep it somewhere else.
DEFAULT_ENV_FILE = "C:\\NUS Courses\\Year 2 Sem 2\\.env"
load_dotenv(os.environ.get("ENV_FILE", DEFAULT_ENV_FILE))

# --- config ---
AWS_REGION = os.environ.get("AWS_REGION", "us-east-1")
# Check the Bedrock console (Model access) for the exact model ID available in your account/region --
# these IDs change as new versions ship, so don't assume this one is current or correct.
MODEL_ID = os.environ.get("MODEL_ID", "anthropic.claude-sonnet-4-5-20250929-v1:0")

bedrock = boto3.client("bedrock-runtime", region_name=AWS_REGION)
storage = LocalJSONStorage()

app = FastAPI()


class ChatRequest(BaseModel):
    student_id: str
    project_id: str = "default"
    phase: str  # one of phases.PHASES keys, e.g. "problem_identification"
    message: str
    image_base64: str | None = None  # optional: sketch/poster upload, raw base64, no data-uri prefix
    image_format: str = "png"  # png | jpeg | webp


@app.post("/chat")
def chat(req: ChatRequest):
    state = storage.get_state(req.student_id, req.project_id)
    turn_count = state.get("turn_count", 0)
    critique_mode = turn_count > 0 and (turn_count % CRITIQUE_EVERY_N_TURNS == 0)

    system_prompt = build_system_prompt(req.phase, critique_mode)

    # Build message history for Bedrock Converse API
    messages = []
    for turn in state.get("history", [])[-12:]:  # keep last ~6 exchanges of context
        messages.append({"role": turn["role"], "content": [{"text": turn["content"]}]})

    user_content = [{"text": req.message}]
    if req.image_base64:
        user_content.append({
            "image": {
                "format": req.image_format,
                "source": {"bytes": base64.b64decode(req.image_base64)},
            }
        })
    messages.append({"role": "user", "content": user_content})

    response = bedrock.converse(
        modelId=MODEL_ID,
        system=[{"text": system_prompt}],
        messages=messages,
        inferenceConfig={"maxTokens": 600, "temperature": 0.7},
    )

    assistant_text = "".join(
        block["text"] for block in response["output"]["message"]["content"] if "text" in block
    )

    new_state = storage.save_turn(req.student_id, req.project_id, req.phase, req.message, assistant_text)

    return {
        "reply": assistant_text,
        "phase": req.phase,
        "critique_mode": critique_mode,
        "turn_count": new_state["turn_count"],
    }


@app.get("/state")
def get_state(student_id: str, project_id: str = "default"):
    return storage.get_state(student_id, project_id)


# Lambda entrypoint (only used when deployed) -- requires `pip install mangum`
try:
    from mangum import Mangum
    handler = Mangum(app)
except ImportError:
    pass