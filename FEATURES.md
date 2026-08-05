# Features implemented

## Backend (`main.py`, FastAPI)
- `POST /chat` -- takes `student_id`, `project_id`, `phase`, `message`, and an optional
  base64 image (sketch/poster), builds the phase's system prompt, sends the last ~6
  exchanges of history plus the new message to Bedrock (`converse` API), saves the turn,
  and returns the reply.
- `GET /state` -- returns saved phase, turn count, and message history for a
  `student_id`/`project_id` pair.
- Image input supports png/jpeg/webp via Bedrock's vision content blocks.
- `.env` loads from outside the repo by default (`ENV_FILE` env var, or
  `~/.config/nus-codesign-chatbot/.env`) so AWS/model config never risks being committed.
- Lambda-ready: `Mangum` handler wraps the app when deployed (see `README_1.md`).

## Phase-specific prompting (`phases.py`)
- Five design-thinking phases, each with its own focus and rubric criteria:
  Problem Identification, Concept Generation, Design Specification,
  Ethics & Critical Thinking, Reflection.
- Every response follows a silent internal structure: interpret the student's message,
  check for unstated assumptions, ask one Socratic question, nudge reflection from
  another angle -- never hands over the answer.
- Silent AT-EAI ethics check (Fairness, Privacy, Transparency, Non-maleficence,
  Responsibility) runs every turn; only surfaced explicitly during the Ethics phase.
- **Critique mode**: every 4th turn in a phase, the assistant switches from questioning
  to a short Strengths / To Develop critique instead of another question.

## Persistence (`storage.py`)
- `LocalJSONStorage`: per-student, per-project state (phase, turn count, message history)
  saved to a local JSON file. Thread-safe via a lock.
- A commented-out `DynamoDBStorage` variant with the same interface is included for
  swapping in once the JSON-file approach needs to survive Lambda cold starts /
  concurrent instances.

## Student UI (`streamlit_app.py`)
- Chat interface (`st.chat_message`) with a distinct highlighted style for critique-mode
  replies vs. normal Socratic questions.
- Sidebar: student ID / project ID fields, a phase picker synced to `phases.py`'s real
  phase keys, and a progress bar showing which of the 5 phases you're on.
- Each phase header shows its focus and an expandable "what this phase is looking for"
  rubric panel.
- "New session" button starts a fresh project bucket without losing prior history.
- "Save chat" downloads the current conversation as a `.txt` transcript.
- Sketch/photo upload with inline preview, sent to the backend as base64.
- History auto-loads from the backend (`GET /state`) whenever student/project changes.
- Friendly inline error if the FastAPI backend isn't reachable, instead of crashing.
- Configurable backend URL (`BACKEND_URL` env var or the sidebar's "Advanced" panel) --
  needed for pointing the UI at a deployed Lambda Function URL instead of localhost.

## Not yet implemented (see `README_1.md` for the deferred roadmap)
- Auth (currently a single shared demo, no Cognito/login)
- Real retrieval (RAG) over course materials -- framework text is pasted directly into
  `phases.py` prompts
- DynamoDB storage (JSON-file storage only; fine for local/demo use)
