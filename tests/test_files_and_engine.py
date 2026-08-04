from pathlib import Path
from types import SimpleNamespace

import pytest

from backend.chat_service import ChatOptions, StudentChatEngine, response_input_for_model
from backend.file_processing import document_context, save_uploads
from backend.student_store import StudentStore


def test_text_assignment_upload_is_saved_and_extracted(tmp_path, monkeypatch):
    from backend import file_processing

    monkeypatch.setattr(file_processing.settings, "files_dir", tmp_path / "files")
    uploads = save_uploads(
        "thread-safe",
        [("brief.txt", b"Compare two theories using evidence.", "text/plain")],
    )
    assert uploads[0].supported is True
    assert uploads[0].path.is_file()
    assert "Compare two theories" in document_context(uploads)


def test_upload_path_and_limits_are_safe(tmp_path, monkeypatch):
    from backend import file_processing

    monkeypatch.setattr(file_processing.settings, "files_dir", tmp_path / "files")
    uploads = save_uploads(
        "../../thread",
        [("../../rubric.txt", b"criteria", "text/plain")],
    )
    assert uploads[0].path.name == "rubric.txt"
    assert (tmp_path / "files") in uploads[0].path.parents

    monkeypatch.setattr(file_processing.settings, "max_file_size_mb", 0)
    with pytest.raises(ValueError, match="exceeds"):
        save_uploads("thread", [("large.txt", b"x", "text/plain")])


def test_model_switch_replays_canonical_history():
    user = {"role": "user", "content": "new"}
    same_input, same_response = response_input_for_model(
        [{"role": "user", "content": "old"}],
        user,
        previous_model="gpt-5.4",
        selected_model="gpt-5.4",
        previous_response_id="resp_1",
    )
    assert same_input == [user]
    assert same_response == "resp_1"

    switched_input, switched_response = response_input_for_model(
        [{"role": "user", "content": "old"}],
        user,
        previous_model="gpt-5.3-chat-latest",
        selected_model="gpt-5.4",
        previous_response_id="resp_old",
    )
    assert [item["content"] for item in switched_input] == ["old", "new"]
    assert switched_response is None


def test_mock_student_turn_streams_and_persists(tmp_path, monkeypatch):
    from backend import chat_service, file_processing

    monkeypatch.setattr(chat_service.settings, "mock_openai", True)
    monkeypatch.setattr(file_processing.settings, "files_dir", tmp_path / "files")
    store = StudentStore(tmp_path / "student.sqlite3", identifier="engine-student")
    engine = StudentChatEngine(store)
    thread_id = store.create_thread(
        model_id="gpt-5.4-mini",
        support_mode="critical-thinking",
    )
    stream = engine.submit(
        thread_id,
        "Is this evidence enough for my conclusion?",
        ChatOptions(
            model_id="gpt-5.4-mini",
            support_mode="critical-thinking",
            assignment={"title": "Research report"},
            thinking_stage="evidence",
            response_detail="long",
        ),
        [("notes.txt", b"Sample size: 12", "text/plain")],
    )
    rendered = "".join(stream)
    assert "critical-thinking pass" in rendered
    assert "student" in rendered.lower()
    messages = store.get_messages(thread_id)
    assert [message["role"] for message in messages] == ["user", "assistant"]
    from backend.models import LOCKED_CHAT_MODEL_ID

    assert messages[-1]["metadata"]["model"] == LOCKED_CHAT_MODEL_ID
    assert messages[-1]["metadata"]["thinking_stage"] == "evidence"
    assert messages[-1]["metadata"]["response_detail"] == "long"
    assert store.get_state(thread_id)["modelId"] == LOCKED_CHAT_MODEL_ID


def test_mock_short_mode_is_concise_and_stage_specific(tmp_path, monkeypatch):
    from backend import chat_service

    monkeypatch.setattr(chat_service.settings, "mock_openai", True)
    store = StudentStore(tmp_path / "student.sqlite3", identifier="short-mode-student")
    engine = StudentChatEngine(store)
    thread_id = store.create_thread(
        model_id="gpt-5.4",
        support_mode="critical-thinking",
    )
    stream = engine.submit(
        thread_id,
        "What assumption should I inspect first?",
        ChatOptions(
            model_id="gpt-5.4",
            thinking_stage="assumptions",
            response_detail="short",
        ),
    )
    rendered = "".join(stream)
    assert "Surface assumptions" in rendered
    assert "**Reflect:**" in rendered
    assert "critical-thinking pass" not in rendered


def test_edit_and_resend_replaces_later_turns_and_uses_revised_prompt(
    tmp_path, monkeypatch
):
    from backend import chat_service

    monkeypatch.setattr(chat_service.settings, "mock_openai", True)
    store = StudentStore(tmp_path / "student.sqlite3", identifier="edit-student")
    engine = StudentChatEngine(store)
    thread_id = store.create_thread(
        model_id="gpt-5.4",
        support_mode="critical-thinking",
    )
    first = engine.submit(
        thread_id,
        "Old prompt",
        ChatOptions(model_id="gpt-5.4"),
    )
    list(first)
    second = engine.submit(
        thread_id,
        "Later prompt",
        ChatOptions(model_id="gpt-5.4"),
    )
    list(second)

    revised = engine.submit(
        thread_id,
        "Revised prompt",
        ChatOptions(
            model_id="gpt-5.4-mini",
            existing_user_message_id=first.user_message_id,
        ),
    )
    rendered = "".join(revised)

    messages = store.get_messages(thread_id)
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[0]["id"] == first.user_message_id
    assert messages[0]["content"] == "Revised prompt"
    assert "Revised prompt" in rendered
    assert "Old prompt" not in rendered
    assert "Later prompt" not in rendered
    assert [item["content"] for item in store.get_state(thread_id)["history"]] == [
        "Revised prompt",
        messages[1]["content"],
    ]


def test_mock_image_generation_returns_downloadable_artifact(tmp_path, monkeypatch):
    from backend import chat_service

    monkeypatch.setattr(chat_service.settings, "mock_openai", True)
    monkeypatch.setattr(chat_service.settings, "workspaces_dir", tmp_path / "workspaces")
    store = StudentStore(tmp_path / "student.sqlite3", identifier="image-student")
    engine = StudentChatEngine(store)
    thread_id = store.create_thread(
        model_id="gpt-5.4",
        support_mode="assignment-planner",
    )
    stream = engine.submit(
        thread_id,
        "Create a concept map image",
        ChatOptions(model_id="gpt-5.4", image_generation=True),
    )
    list(stream)
    assert len(stream.artifacts) == 1
    assert stream.artifacts[0].is_file()
    assert stream.artifacts[0].suffix == ".svg"


def test_responses_stream_web_sources_and_state_without_live_api(tmp_path, monkeypatch):
    from backend import chat_service

    class Usage:
        def model_dump(self, mode="json"):
            assert mode == "json"
            return {"input_tokens": 20, "output_tokens": 8}

    completed = SimpleNamespace(
        id="resp_streamed",
        usage=Usage(),
        output=[
            SimpleNamespace(
                content=[
                    SimpleNamespace(
                        annotations=[
                            SimpleNamespace(
                                url="https://example.edu/source",
                                title="Primary source",
                            )
                        ]
                    )
                ]
            )
        ],
    )

    events = [
        SimpleNamespace(
            type="response.created",
            response=SimpleNamespace(id="resp_streamed"),
        ),
        SimpleNamespace(type="response.output_text.delta", delta="Evidence "),
        SimpleNamespace(type="response.output_text.delta", delta="matters."),
        SimpleNamespace(type="response.completed", response=completed),
    ]

    class FakeResponses:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return iter(events)

    fake_responses = FakeResponses()
    fake_client = SimpleNamespace(responses=fake_responses)
    monkeypatch.setattr(chat_service, "OpenAI", lambda **_: fake_client)
    monkeypatch.setattr(chat_service.settings, "mock_openai", False)
    monkeypatch.setattr(chat_service.settings, "openai_api_key", "test-key")

    store = StudentStore(tmp_path / "student.sqlite3", identifier="stream-student")
    engine = StudentChatEngine(store)
    thread_id = store.create_thread(
        model_id="gpt-5.4",
        support_mode="evidence-review",
    )
    stream = engine.submit(
        thread_id,
        "Find current evidence.",
        ChatOptions(
            model_id="gpt-5.4",
            support_mode="evidence-review",
            web_search=True,
        ),
    )
    assert "".join(stream) == "Evidence matters."
    assert stream.sources == [
        {"url": "https://example.edu/source", "title": "Primary source"}
    ]
    from backend.models import LOCKED_CHAT_MODEL_ID

    assert fake_responses.kwargs["model"] == LOCKED_CHAT_MODEL_ID
    assert fake_responses.kwargs["tools"] == [{"type": "web_search"}]
    assert fake_responses.kwargs["include"] == ["web_search_call.action.sources"]
    assert store.get_state(thread_id)["previousResponseId"] == "resp_streamed"
