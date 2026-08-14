"""
CDE2300 Socratic Design Thinking Coach -- Streamlit student UI.

This is a thin client: all AI logic, prompts, and persistence live in the AgentCore Runtime
(NUSCodesignChatbot/app/chatbot_harnessAgent). Chat history is durable server-side (AgentCore
Memory, keyed by student_id + session_id) -- this app is just a window onto it.

Run:
    streamlit run streamlit_app.py

Uses whatever AWS credentials are already configured locally (same as the aws CLI). Override the
target runtime with the AGENT_RUNTIME_ARN env var if needed.
"""

import json
import os
import uuid

import boto3
import streamlit as st
from botocore.exceptions import BotoCoreError, ClientError

AGENT_RUNTIME_ARN = os.environ.get(
    "AGENT_RUNTIME_ARN",
    "arn:aws:bedrock-agentcore:us-west-2:355604674280:runtime/NUSCodesignChatbot_chatbot_harnessAgent-6ncEO79sD7",
)
AWS_REGION = os.environ.get("AWS_REGION", "us-west-2")
MEMORY_ID = os.environ.get("MEMORY_ID", "NUSCodesignChatbot_StudentChatHistory-jtaN1sD4xC")

PHASES_UI = {
    "qa": {
        "label": "Q&A",
        "blurb": "Ask about course content, deadlines, rubrics -- answered from official CDE2300 course materials.",
    },
    "coaching": {
        "label": "Coaching",
        "blurb": "Socratic design-thinking coaching. The bot asks probing questions -- it won't give you the answer.",
    },
    "scoring": {
        "label": "Scoring",
        "blurb": "Get a Strengths / To Develop critique of your thinking so far in this conversation.",
    },
}
PHASE_ORDER = ["qa", "coaching", "scoring"]

COACHING_TOPICS_UI = {
    "problem_identification": "Problem Identification",
    "concept_generation": "Concept Generation",
    "design_specification": "Design Specification",
    "ethics_critical": "Ethics & Critical Thinking",
    "reflection": "Reflection",
}
COACHING_TOPIC_ORDER = list(COACHING_TOPICS_UI.keys())

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


@st.cache_resource
def get_client():
    return boto3.client("bedrock-agentcore", region_name=AWS_REGION)


def new_session_id() -> str:
    # AWS requires runtimeSessionId to be at least 33 characters.
    return f"streamlit-{uuid.uuid4().hex}"


# --- session state defaults ---
def _init_state():
    defaults = {
        "student_id": "demo-student",
        "session_id": new_session_id(),
        "phase": "qa",
        "topic": COACHING_TOPIC_ORDER[0],
        "messages": [],  # list of {role, content, critique}
        "hydrated_for": None,
    }
    for key, value in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = value


_init_state()


def hydrate_history():
    """Pull saved history for the current student/session from AgentCore Memory."""
    try:
        resp = get_client().list_events(
            memoryId=MEMORY_ID,
            actorId=st.session_state.student_id,
            sessionId=st.session_state.session_id,
            maxResults=100,
        )
    except (ClientError, BotoCoreError):
        st.session_state.messages = []
        return

    turns = []
    for event in reversed(resp.get("events", [])):  # API returns newest-first
        for item in event.get("payload", []):
            conversational = item.get("conversational")
            if not conversational:
                continue  # skip blob entries (session/agent-state bookkeeping, not chat turns)
            role = conversational.get("role", "").lower()
            text = conversational.get("content", {}).get("text")
            if role in ("user", "assistant") and text:
                turns.append({"role": role, "content": text, "critique": False})
    st.session_state.messages = turns


def stream_reply(prompt: str):
    """Invoke the agent and yield reply text chunks as they arrive."""
    payload = {"prompt": prompt, "phase": st.session_state.phase}
    if st.session_state.phase == "coaching":
        payload["topic"] = st.session_state.topic
    if st.session_state.student_id:
        payload["student_id"] = st.session_state.student_id

    response = get_client().invoke_agent_runtime(
        agentRuntimeArn=AGENT_RUNTIME_ARN,
        payload=json.dumps(payload).encode("utf-8"),
        runtimeSessionId=st.session_state.session_id,
    )
    for line in response["response"].iter_lines():
        if not line:
            continue
        line = line.decode("utf-8") if isinstance(line, bytes) else line
        if not line.startswith("data: "):
            continue
        event = json.loads(line[len("data: "):])
        text = event.get("event", {}).get("contentBlockDelta", {}).get("delta", {}).get("text")
        if text:
            yield text


# --- sidebar ---
with st.sidebar:
    st.markdown("## 🧭 Design Thinking Coach")
    st.caption("CDE2300 Socratic AI assistant (AgentCore)")

    with st.expander("Session", expanded=True):
        student_id = st.text_input("Student ID", value=st.session_state.student_id)
        if student_id != st.session_state.student_id:
            st.session_state.student_id = student_id
            st.session_state.hydrated_for = None
            st.rerun()
        st.caption(f"Session: `{st.session_state.session_id[:24]}...`")

    st.markdown("### Phase")
    phase_labels = [PHASES_UI[key]["label"] for key in PHASE_ORDER]
    current_index = PHASE_ORDER.index(st.session_state.phase)
    chosen_label = st.radio(
        "Choose the phase you're working on",
        options=phase_labels,
        index=current_index,
        label_visibility="collapsed",
    )
    st.session_state.phase = PHASE_ORDER[phase_labels.index(chosen_label)]

    if st.session_state.phase == "coaching":
        topic_labels = [COACHING_TOPICS_UI[key] for key in COACHING_TOPIC_ORDER]
        topic_index = COACHING_TOPIC_ORDER.index(st.session_state.topic)
        chosen_topic_label = st.selectbox("Coaching topic", options=topic_labels, index=topic_index)
        st.session_state.topic = COACHING_TOPIC_ORDER[topic_labels.index(chosen_topic_label)]

    st.divider()

    col_new, col_save = st.columns(2)
    with col_new:
        if st.button("🔄 New session", use_container_width=True):
            st.session_state.session_id = new_session_id()
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
            file_name=f"{st.session_state.student_id}_{st.session_state.session_id}.txt",
            mime="text/plain",
            use_container_width=True,
        )


# --- hydrate history when student/session changes ---
hydration_key = (st.session_state.student_id, st.session_state.session_id)
if st.session_state.hydrated_for != hydration_key:
    hydrate_history()
    st.session_state.hydrated_for = hydration_key


# --- main header ---
phase = PHASES_UI[st.session_state.phase]
header = phase["label"]
if st.session_state.phase == "coaching":
    header += f" — {COACHING_TOPICS_UI[st.session_state.topic]}"
st.title(header)
st.markdown(f'<div class="phase-desc">{phase["blurb"]}</div>', unsafe_allow_html=True)

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

prompt = st.chat_input("Type your response...")

if prompt:
    st.session_state.messages.append({"role": "user", "content": prompt, "critique": False})
    with st.chat_message("user", avatar="🧑‍🎓"):
        st.markdown(prompt)

    with st.chat_message("assistant", avatar="🧭"):
        try:
            reply = st.write_stream(stream_reply(prompt))
        except (ClientError, BotoCoreError) as exc:
            reply = (
                f"⚠️ Couldn't reach the AgentCore runtime `{AGENT_RUNTIME_ARN}`. "
                f"Check your AWS credentials and that the runtime is deployed.\n\nDetails: {exc}"
            )
            st.markdown(reply)

    st.session_state.messages.append(
        {"role": "assistant", "content": reply, "critique": st.session_state.phase == "scoring"}
    )
