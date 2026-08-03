from pathlib import Path

from backend.student_store import StudentStore


def make_store(tmp_path: Path) -> StudentStore:
    return StudentStore(tmp_path / "student.sqlite3", identifier="test-student")


def test_chat_history_folders_feedback_and_state(tmp_path):
    store = make_store(tmp_path)
    thread_id = store.create_thread(
        model_id="gpt-5.3-chat-latest",
        support_mode="critical-thinking",
        assignment={"title": "Essay"},
    )
    user_id = store.add_message(
        thread_id,
        "user",
        "Evaluate my central claim",
        model_id="gpt-5.3-chat-latest",
    )
    assistant_id = store.add_message(
        thread_id,
        "assistant",
        "Start by separating the claim from its evidence.",
        model_id="gpt-5.3-chat-latest",
    )
    store.set_feedback(thread_id, assistant_id, 1)
    folder_id = store.create_folder("Semester 1")
    store.move_thread(thread_id, folder_id)
    store.save_state(
        thread_id,
        previous_response_id="resp_1",
        model_id="gpt-5.3-chat-latest",
        history=[{"role": "user", "content": "Evaluate my central claim"}],
    )
    store.record_turn(
        thread_id,
        user_id,
        assistant_id,
        "gpt-5.3-chat-latest",
        None,
        {"input_tokens": 5},
    )

    thread = store.get_thread(thread_id)
    assert thread["folderId"] == folder_id
    assert thread["name"] == "Evaluate Central Claim"
    assert store.list_threads("central")[0]["id"] == thread_id
    overview = store.list_threads(folder_id=folder_id)[0]
    assert overview["id"] == thread_id
    assert overview["folderName"] == "Semester 1"
    assert overview["messageCount"] == 2
    assert overview["studentTurnCount"] == 1
    assert overview["helpfulCount"] == 1
    assert overview["needsReviewCount"] == 0
    assert overview["latestUserMessage"] == "Evaluate my central claim"
    messages = store.get_messages(thread_id)
    assert [message["role"] for message in messages] == ["user", "assistant"]
    assert messages[-1]["feedback"] == 1
    assert store.get_state(thread_id)["previousResponseId"] == "resp_1"


def test_folder_delete_moves_chat_to_unfiled(tmp_path):
    store = make_store(tmp_path)
    thread_id = store.create_thread(
        model_id="gpt-5.4",
        support_mode="assignment-planner",
    )
    folder_id = store.create_folder("Assignments")
    store.move_thread(thread_id, folder_id)
    store.delete_folder(folder_id)
    assert store.get_thread(thread_id)["folderId"] is None
    assert store.list_threads(folder_id="__unfiled__")[0]["id"] == thread_id


def test_thread_rename_edit_and_delete(tmp_path):
    store = make_store(tmp_path)
    thread_id = store.create_thread(
        model_id="gpt-5.4-mini",
        support_mode="writing-feedback",
    )
    message_id = store.add_message(thread_id, "user", "Original")
    store.update_message(message_id, "Revised")
    store.update_thread(thread_id, name="Draft feedback")
    assert store.get_messages(thread_id)[0]["content"] == "Revised"
    assert store.get_thread(thread_id)["name"] == "Draft feedback"
    store.delete_thread(thread_id)
    assert store.get_thread(thread_id) is None


def test_revise_user_message_truncates_later_turns_and_resets_state(tmp_path):
    store = make_store(tmp_path)
    thread_id = store.create_thread(
        model_id="gpt-5.4",
        support_mode="critical-thinking",
    )
    first_user = store.add_message(thread_id, "user", "Old first prompt")
    first_assistant = store.add_message(thread_id, "assistant", "Old answer")
    second_user = store.add_message(thread_id, "user", "Later prompt")
    second_assistant = store.add_message(thread_id, "assistant", "Later answer")
    store.record_turn(thread_id, first_user, first_assistant, "gpt-5.4", None, {})
    store.record_turn(thread_id, second_user, second_assistant, "gpt-5.4", None, {})
    store.save_state(
        thread_id,
        previous_response_id="resp_old",
        model_id="gpt-5.4",
        history=[
            {"role": "user", "content": "Old first prompt"},
            {"role": "assistant", "content": "Old answer"},
            {"role": "user", "content": "Later prompt"},
            {"role": "assistant", "content": "Later answer"},
        ],
    )

    history = store.revise_user_message(
        thread_id,
        first_user,
        "Revised first prompt",
        model_id="gpt-5.4-mini",
        metadata={"thinking_stage": "focus"},
    )

    assert history == []
    messages = store.get_messages(thread_id)
    assert len(messages) == 1
    assert messages[0]["id"] == first_user
    assert messages[0]["content"] == "Revised first prompt"
    assert messages[0]["metadata"]["model"] == "gpt-5.4-mini"
    state = store.get_state(thread_id)
    assert state["previousResponseId"] is None
    assert state["modelId"] is None
    assert state["history"] == []
