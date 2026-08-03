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

## Run the local LangGraph demonstration

This starts the FastAPI boundary and the Streamlit UI together. It is the
recommended professor demonstration mode: it uses the deterministic local
provider by default and automatically advances the Thinking Path after a
validated stage recommendation. Set `AUTO_ADVANCE_STAGES=false` to restore the
student-confirmation flow.

```bash
cd "Co-design Chatbot"
source .venv/bin/activate
cp .env.example .env
sh scripts/run_local_demo.sh
```

For a local model, install [Ollama](https://ollama.com/), then run:

```bash
ollama pull gpt-oss:20b
MODEL_PROVIDER=ollama sh scripts/run_local_demo.sh
```

The local API runs at [http://127.0.0.1:8000/api/v1/health](http://127.0.0.1:8000/api/v1/health).
Use `MODEL_PROVIDER=openai` only after explicitly deciding to run paid OpenAI
requests and configuring `OPENAI_API_KEY`.

In mock mode, the first contribution receives guidance and the follow-up moves
to the next stage. OpenAI and Ollama providers generate the structured stage
recommendation from the student's reasoning.

Course materials are synchronized from `lecture_notes/lectureNotes/` and
`lecture_notes/readings/`, then displayed as locked **Lecture Notes** and
**Readings** groups in Sources. Students can select and preview these materials,
but the app does not offer download or delete controls for instructor-managed
files. The original files are never moved or modified.
Trusted local course files may be up to 50 MB; the student composer retains its
25 MB upload limit.

## Lecture-notes RAG folder

Place PDFs, Word documents, PowerPoint decks, spreadsheets, text files, or
images in `lecture_notes/`. The Sources panel automatically copies new or
changed files into the active notebook, selects them, extracts readable text,
and includes them in the next grounded response. Removing a file from the
folder removes only its synchronized notebook copy on the next refresh.

Lecture-note contents are ignored by Git. `README.txt` remains as the safe  
folder instruction file and is never imported as a source. Each file retains  
the 25 MB limit; up to 50 lecture-note files are synchronized by default.

## Tests

```bash
source .venv/bin/activate
python -m pytest
python -m compileall -q backend streamlit_app.py
```

The suite covers the student-support prompts, academic-integrity guardrails, model registry,  
reasoning compatibility, model/source replay, persistent notebook/folder/feedback state,  
source CRUD and selection, safe URL imports, legacy attachment migration, upload safety,  
mock streaming, generated media, citations, and the multimodal Streamlit composer

