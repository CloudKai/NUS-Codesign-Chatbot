"""
CDE2300 Socratic Design Thinking Coach -- Streamlit student UI.

This is a thin client: all AI logic, prompts, and persistence live in the FastAPI
backend (main.py). Run both:

    uvicorn main:app --reload --port 8000
    streamlit run streamlit_app.py

The backend URL defaults to http://localhost:8000 and can be overridden with the
BACKEND_URL environment variable or the "Advanced" panel in the sidebar.
"""

import os
import uuid

import requests
import streamlit as st

from phases import PHASES

PHASE_ORDER = list(PHASES.keys())
DEFAULT_BACKEND_URL = os.environ.get("BACKEND_URL", "http://localhost:8000")

st.set_page_config(
    page_title="Design Thinking Coach",
    page_icon="🧭",
    layout="wide",
)

st.markdown(
    """
    <style>
    .critique-box {
        border: 1px solid rgba(195, 155, 47, 0.45);
        background: rgba(195, 155, 47, 0.08);
        border-radius: 12px;
        padding: 0.9rem 1.1rem;
        margin-bottom: 0.4rem;
    }
    .critique-label {
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
        color: #a97f16;
        margin-bottom: 0.35rem;
    }
    .phase-desc {
        color: var(--text-color, inherit);
        opacity: 0.8;
        font-size: 0.95rem;
    }
    </style>
    """,
    unsafe_allow_html=True,
)


# --- session state defaults ---
def _init_state():
    defaults = {
        "student_id": "demo-student",
        "project_id": "default",
        "phase": PHASE_ORDER[0],
        "messages": [],  # list of {role, content, critique}
        "hydrated_for": None,
        "uploader_key": 0,
        "backend_url": DEFAULT_BACKEND_URL,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


_init_state()


def hydrate_history():
    """Pull saved history for the current student/project from the backend."""
    try:
        resp = requests.get(
            f"{st.session_state.backend_url}/state",
            params={
                "student_id": st.session_state.student_id,
                "project_id": st.session_state.project_id,
            },
            timeout=15,
        )
        resp.raise_for_status()
        data = resp.json()
    except requests.exceptions.RequestException:
        st.session_state.messages = []
        return False

    st.session_state.messages = [
        {"role": turn["role"], "content": turn["content"], "critique": False}
        for turn in data.get("history", [])
    ]
    if data.get("phase") in PHASES:
        st.session_state.phase = data["phase"]
    return True


# --- sidebar ---
with st.sidebar:
    st.markdown("## 🧭 Design Thinking Coach")
    st.caption("CDE2300 Socratic AI assistant")

    with st.expander("Session", expanded=True):
        student_id = st.text_input("Student ID", value=st.session_state.student_id)
        project_id = st.text_input("Project ID", value=st.session_state.project_id)
        if (student_id, project_id) != (st.session_state.student_id, st.session_state.project_id):
            st.session_state.student_id = student_id
            st.session_state.project_id = project_id
            st.session_state.hydrated_for = None
            st.rerun()

    st.markdown("### Design phase")
    phase_labels = [PHASES[key]["label"] for key in PHASE_ORDER]
    current_index = PHASE_ORDER.index(st.session_state.phase)
    chosen_label = st.radio(
        "Choose the phase you're working on",
        options=phase_labels,
        index=current_index,
        label_visibility="collapsed",
    )
    st.session_state.phase = PHASE_ORDER[phase_labels.index(chosen_label)]

    progress = (PHASE_ORDER.index(st.session_state.phase) + 1) / len(PHASE_ORDER)
    st.progress(progress, text=f"Phase {PHASE_ORDER.index(st.session_state.phase) + 1} of {len(PHASE_ORDER)}")

    st.divider()

    col_new, col_save = st.columns(2)
    with col_new:
        if st.button("🔄 New session", use_container_width=True):
            st.session_state.project_id = f"session-{uuid.uuid4().hex[:8]}"
            st.session_state.messages = []
            st.session_state.hydrated_for = None
            st.rerun()
    with col_save:
        transcript = "\n\n".join(
            f"{'You' if m['role'] == 'user' else 'Coach'}: {m['content']}"
            for m in st.session_state.messages
        )
        st.download_button(
            "💾 Save chat",
            data=transcript or "No messages yet.",
            file_name=f"{st.session_state.student_id}_{st.session_state.project_id}.txt",
            mime="text/plain",
            use_container_width=True,
        )

    with st.expander("Advanced"):
        st.session_state.backend_url = st.text_input("Backend URL", value=st.session_state.backend_url)


# --- hydrate history when student/project changes ---
hydration_key = (st.session_state.student_id, st.session_state.project_id, st.session_state.backend_url)
if st.session_state.hydrated_for != hydration_key:
    hydrate_history()
    st.session_state.hydrated_for = hydration_key


# --- main header ---
phase = PHASES[st.session_state.phase]
st.title(phase["label"])
st.markdown(f'<div class="phase-desc">{phase["core_focus"]}</div>', unsafe_allow_html=True)
with st.expander("What this phase is looking for"):
    st.markdown(phase["rubric_criteria"])

st.divider()

# --- chat history ---
for msg in st.session_state.messages:
    avatar = "🧑‍🎓" if msg["role"] == "user" else "🧭"
    with st.chat_message(msg["role"], avatar=avatar):
        if msg.get("critique"):
            st.markdown(
                f'<div class="critique-box"><div class="critique-label">📝 Critique</div>{msg["content"]}</div>',
                unsafe_allow_html=True,
            )
        else:
            st.markdown(msg["content"])

# --- image attachment ---
uploaded_file = st.file_uploader(
    "📎 Attach a sketch or photo (optional)",
    type=["png", "jpg", "jpeg", "webp"],
    key=f"uploader_{st.session_state.uploader_key}",
)
if uploaded_file is not None:
    st.image(uploaded_file, width=160)

prompt = st.chat_input("Type your response...")

if prompt:
    payload = {
        "student_id": st.session_state.student_id,
        "project_id": st.session_state.project_id,
        "phase": st.session_state.phase,
        "message": prompt,
    }
    if uploaded_file is not None:
        import base64

        payload["image_base64"] = base64.b64encode(uploaded_file.getvalue()).decode("utf-8")
        payload["image_format"] = uploaded_file.type.split("/")[-1] or "png"

    st.session_state.messages.append({"role": "user", "content": prompt, "critique": False})

    try:
        with st.spinner("Thinking..."):
            resp = requests.post(f"{st.session_state.backend_url}/chat", json=payload, timeout=60)
            resp.raise_for_status()
            data = resp.json()
        st.session_state.messages.append(
            {"role": "assistant", "content": data["reply"], "critique": data.get("critique_mode", False)}
        )
    except requests.exceptions.RequestException as exc:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": (
                    f"⚠️ Couldn't reach the assistant backend at `{st.session_state.backend_url}`. "
                    f"Is it running? (`uvicorn main:app --reload --port 8000`)\n\nDetails: {exc}"
                ),
                "critique": False,
            }
        )

    st.session_state.uploader_key += 1
    st.rerun()
