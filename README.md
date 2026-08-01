# Co-design Student Chatbot

Co-design is a **Streamlit** learning assistant for university students. It includes an
OpenAI model registry, Responses API conversation logic, SQLite history, folders, model
switching, attachments, and a local analysis foundation.

There is no authentication and there is no Replit dependency. Student data is stored locally.

## Student experience

- A NotebookLM-inspired research workspace with dedicated Sources, Chat, and Learning
  Studio panels, adaptive light and dark themes, and mobile panel switching.
- Notebook history and folders are available from the top bar. Every notebook shows its
  current thinking stage, journey progress, student contribution count, concise learning
  summary, and feedback status.
- A persistent source library for uploaded files, pasted text, and safely imported public
  webpages. Students can select exactly which sources ground each response, preview them,
  download originals, and open source citations from assistant messages.
- A six-stage critical-thinking journey: Focus, Evidence, Assumptions, Perspectives,
  Synthesis, and Conclusion.
- Coach-controlled stage progression that evaluates each student contribution automatically,
  alongside a focused Learning Review of the student’s developing understanding.
- Short and Long response modes, persisted with each chat and applied to every model.
- An on-demand Learning Review showing chat contributions, completed stages, the current
  critical-understanding level, conclusion, reflection, and next question.
- A fixed Critical Thinking Coach mode with no learning-mode or advanced-settings clutter.
- Explicit academic-integrity guidance that protects student authorship and never fabricates
  sources, evidence, quotations, experiments, or citations.
- Model selection before every message, capability-aware reasoning levels, a visible Legacy
  label, exact-model execution, and no silent model fallback.
- Streaming responses, persistent anonymous chat history, search, folders, rename, move,
  delete, edit, regenerate, and transcript download.
- A single composer for text, files, images, and voice. Composer attachments are added to
  the notebook source library automatically.
- Common document, presentation, spreadsheet, image, and text formats: up to 10 files and
  25 MB each by default.
- A full mock mode so instructors and students can explore the UI without an API key.

## Architecture

```text
Streamlit UI (streamlit_app.py)
        |
        +-- backend/student_support.py  learning modes + critical-thinking foundation
        +-- backend/student_journey.py  stages + reflections + learning reviews
        +-- backend/chat_service.py     Responses API streaming + tools + model replay
        +-- backend/student_store.py    SQLite chats, folders, feedback, model state
        +-- backend/source_library.py   notebook sources + URL safety + grounding context
        +-- backend/file_processing.py  safe uploads + local assignment extraction
        +-- backend/models.py           curated per-message model registry
```

The OpenAI backend uses the Responses API for multi-turn, tool-using workflows. Canonical
history is replayed when a student changes models or the selected source set changes;
`previous_response_id` is reused only while both the model and source snapshot remain the
same.

## Run the UI

Python 3.12 or newer is recommended.

```bash
cd "Co-design Chatbot"
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
sh scripts/run.sh
```

Open [http://localhost:8501](http://localhost:8501).

`MOCK_OPENAI=true` is the default, so the complete local interface works immediately without
an API key.

## Use live OpenAI responses

Edit `.env`:

```env
MOCK_OPENAI=false
OPENAI_API_KEY=your_api_key
DEFAULT_CHAT_MODEL=gpt-5.3-chat-latest
```

Restart Streamlit. API model access varies by OpenAI project. If the selected model is not
available, Co-design shows the exact error and asks the student to choose another model; it
does not silently substitute one.

The current OpenAI model catalog and Responses guidance are available in the
[official model documentation](https://developers.openai.com/api/docs/models) and
[model guidance](https://developers.openai.com/api/docs/guides/latest-model).

## Tests

```bash
source .venv/bin/activate
python -m pytest
python -m compileall -q backend streamlit_app.py
```

The suite covers the student-support prompts, academic-integrity guardrails, model registry,
reasoning compatibility, model/source replay, persistent notebook/folder/feedback state,
source CRUD and selection, safe URL imports, legacy attachment migration, upload safety,
mock streaming, generated media, citations, and the multimodal Streamlit composer.
# NUS-Solo-Codesign
