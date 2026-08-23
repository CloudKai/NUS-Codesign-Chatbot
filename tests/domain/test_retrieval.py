"""Deterministic retrieval quality, isolation, and adapter-boundary tests."""

from __future__ import annotations

import pytest

from backend.application import CoachApplicationService
from backend.chat_service import ChatOptions, StudentChatEngine
from backend.coaching.mode_policy import QA_EVIDENCE_GAP_RESPONSE
from backend.domain import (
    CitationReference,
    CoachRequest,
    ProviderAssessmentResult,
    RetrievalChunkReference,
    StageDecision,
)
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.repositories import SQLiteNotebookRepository, SQLitePhaseTransitionRepository
from backend.retrieval import (
    CompositeContextRetriever,
    COURSE_RETRIEVAL_UNAVAILABLE_CONTEXT,
    LocalChunkRetriever,
    RetrievalQuery,
    RetrievalResult,
    RetrievalSource,
    RetrievedChunk,
    UNANALYZABLE_SOURCE_PLACEHOLDER,
    bounded_retrieval_result,
    contextual_course_query_text,
    course_material_id_collisions,
    course_material_id_from_object_key,
    expand_session_query_text,
    focused_excerpt,
    prefer_session_matching_sources,
    retrieval_sources_from_notebook,
)
from backend.source_library import (
    CHAT_ATTACHMENT_ORIGIN,
    add_file_sources,
    add_text_source,
    image_inputs_for_source_ids,
)
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow


def test_focused_excerpt_never_exceeds_limit_with_ellipsis_window():
    padding = "Background crossing design notes without the target claim. " * 40
    target = "Safer pedestrian crossings for older adults near schools need evidence."
    excerpt = focused_excerpt(
        padding + target + padding,
        "older adults pedestrian crossings evidence",
        limit=600,
    )

    assert 0 < len(excerpt) <= 600
    assert excerpt.startswith("…")
    assert excerpt.endswith("…")
    assert "older adults" in excerpt.casefold()
    RetrievalChunkReference(
        source_id="src",
        label="S1",
        title="Crossing note",
        chunk_id="S1-C0",
        excerpt=excerpt,
    )


def test_application_persists_mid_chunk_excerpt_within_domain_limit(tmp_path):
    class _MidChunkRetriever:
        def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
            source = query.sources[0]
            padding = "Background crossing design notes without the target claim. " * 40
            target = (
                "Safer pedestrian crossings for older adults near schools need evidence."
            )
            return bounded_retrieval_result(
                [
                    RetrievedChunk(
                        source_id=source.source_id,
                        label=source.label,
                        title=source.title,
                        chunk_id=f"{source.label}-C0",
                        text=padding + target + padding,
                        score=1.0,
                        source_index=1,
                        chunk_index=0,
                    )
                ]
            )

    store = StudentStore(tmp_path / "mid-chunk-excerpt.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, notebook, "Crossing note", "Selected crossing source")
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(DeterministicCoachProvider(), transitions),
        LearningProgressService(store, notebooks, transitions),
        retriever=_MidChunkRetriever(),
    )

    turn = service.submit(
        CoachRequest(
            thread_id=notebook,
            student_message="Which older-adult crossing trade-off still needs evidence?",
            current_stage="problem_identification",
            response_detail="short",
        )
    )

    refs = store.get_messages(notebook)[-1]["metadata"]["retrieval_refs"]
    assert refs
    assert len(refs[0]["excerpt"]) <= 600
    assert "older adults" in refs[0]["excerpt"].casefold()
    assert turn.response_text


def _source(
    source_id: str,
    label: str,
    title: str,
    text: str,
    *,
    kind: str = "file",
) -> RetrievalSource:
    return RetrievalSource(
        source_id=source_id,
        label=label,
        title=title,
        text=text,
        kind=kind,
    )


def test_local_retriever_finds_relevant_late_document_chunk():
    padding = "General introductory material without the target topic. " * 45
    target = (
        "Thermal battery degradation accelerates above 45 degrees Celsius. "
        "The reported capacity loss was 18 percent after 500 cycles."
    )
    sources = (
        _source("battery", "S1", "Battery study", padding + target),
        _source(
            "crossing",
            "S2",
            "Road design note",
            "Pedestrian crossings need visible signals and sufficient timing. " * 20,
        ),
    )
    result = LocalChunkRetriever(
        chunk_chars=500,
        overlap_chars=80,
        max_chunks=3,
    ).retrieve(
        RetrievalQuery(
            current_message="What evidence quantifies thermal battery degradation?",
            current_stage="concept_generation",
            sources=sources,
        )
    )

    assert result.chunks
    assert result.chunks[0].source_id == "battery"
    assert "18 percent after 500 cycles" in result.context
    assert "Road design note" not in result.context
    assert len(result.context) < len(padding + target)


def test_local_retriever_preserves_stable_labels_and_source_diversity():
    sources = (
        _source(
            "survey",
            "S1",
            "Survey",
            "Older adults reported insufficient crossing time in the survey.",
        ),
        _source(
            "audit",
            "S2",
            "Street audit",
            "The crossing audit measured insufficient signal timing for older adults.",
        ),
    )
    result = LocalChunkRetriever(max_chunks=4).retrieve(
        RetrievalQuery(
            current_message="What evidence concerns crossing time for older adults?",
            current_stage="concept_generation",
            sources=sources,
        )
    )

    assert {chunk.source_id for chunk in result.chunks} == {"survey", "audit"}
    assert {chunk.label for chunk in result.chunks} == {"S1", "S2"}
    assert "[S1] Survey" in result.context
    assert "[S2] Street audit" in result.context


def test_expand_session_query_text_aliases_lecture_and_week():
    assert expand_session_query_text("what is lecture 1 about") == (
        "what is lecture 1 about week 1"
    )
    assert expand_session_query_text("summarise Week 1") == "summarise Week 1 lecture 1"
    assert expand_session_query_text("what is innovation?") == "what is innovation?"
    assert expand_session_query_text(
        "what are the week 1 contents talking about?"
    ) == "what are the week 1 contents talking about? lecture 1"
    assert expand_session_query_text("what are lecture 1 slides about?") == (
        "what are lecture 1 slides about? week 1"
    )
    assert "week 1" in expand_session_query_text("week1")
    assert "lecture 1" in expand_session_query_text("week1")
    assert "week 1" in expand_session_query_text("lecture01")
    assert "lecture 1" in expand_session_query_text("lecture01")


def test_contextual_course_query_uses_prior_substantive_reasoning_not_lookup_chain():
    """Anaphoric lookups skip acknowledgements and earlier source questions."""
    reasoning = (
        "I think reliability matters more than convenience because a false negative "
        "could leave someone in the road."
    )
    query = RetrievalQuery(
        current_message="Does another reading support my previous point?",
        current_stage="deep_analysis",
        sources=(),
        recent_messages=(
            {"role": "user", "content": reasoning},
            {"role": "assistant", "content": "What evidence supports that?"},
            {"role": "user", "content": "Which reading supports what I just said?"},
            {"role": "user", "content": "okay"},
        ),
    )

    text = contextual_course_query_text(query)

    assert "Current source question: Does another reading" in text
    assert reasoning in text
    assert "Which reading supports what I just said?" not in text
    assert "okay" not in text


def test_contextual_course_query_recognizes_my_statement_as_anaphoric():
    """Student wording from the production course-support question stays grounded."""
    reasoning = "The crossing should prioritise reliable access over convenience."
    query = RetrievalQuery(
        current_message="Which lecture materials or readings support my statement?",
        current_stage="deep_analysis",
        sources=(),
        recent_messages=({"role": "user", "content": reasoning},),
    )

    assert reasoning in contextual_course_query_text(query)


def test_contextual_course_query_ignores_inactive_and_attachment_only_messages():
    """Only active user reasoning can become a retrieval antecedent."""
    active = "Our stakeholder needs a safe crossing with enough signal time."
    query = RetrievalQuery(
        current_message="Which lecture supports what I just said?",
        current_stage="problem_identification",
        sources=(),
        recent_messages=(
            {"role": "user", "content": "Old superseded argument", "active": False},
            {"role": "user", "content": "Please summarise this attached PDF."},
            {"role": "user", "content": active},
        ),
    )

    text = contextual_course_query_text(query)

    assert active in text
    assert "Old superseded argument" not in text
    assert "attached PDF" not in text


def test_contextual_course_query_keeps_reasoning_that_mentions_an_attachment():
    """Attachment references do not discard an otherwise substantive point."""
    reasoning = (
        "The attached PDF shows older pedestrians need a longer crossing interval, "
        "so reliability should matter more than convenience."
    )
    query = RetrievalQuery(
        current_message="Which reading supports what I just said?",
        current_stage="problem_identification",
        sources=(),
        recent_messages=(
            {"role": "user", "content": "Please summarise this attached PDF."},
            {"role": "user", "content": reasoning},
        ),
    )

    text = contextual_course_query_text(query)

    assert reasoning in text


def test_contextual_course_query_is_bounded_and_uses_relevant_summary_only():
    """Question and antecedent take priority; summary fills only spare budget."""
    antecedent = "reliability " * 300
    query = RetrievalQuery(
        current_message="Which reading supports my previous point about reliability?",
        current_stage="deep_analysis",
        sources=(),
        project_context="Reliability evidence should guide the crossing threshold.",
        conversation_summary="Unrelated typography and colour discussion.",
        recent_messages=({"role": "user", "content": antecedent},),
    )

    text = contextual_course_query_text(query, max_chars=500, antecedent_max_chars=800)

    assert len(text) <= 500
    assert "Current source question:" in text
    assert "Prior student reasoning:" in text
    assert "Unrelated typography" not in text


def test_direct_course_query_keeps_its_existing_query_text():
    """Non-anaphoric Week/Lecture queries do not gain hidden context."""
    query = RetrievalQuery(
        current_message="What is lecture 1 about?",
        current_stage="problem_identification",
        sources=(),
        recent_messages=(
            {"role": "user", "content": "My earlier design reasoning."},
        ),
    )
    assert contextual_course_query_text(query) == "What is lecture 1 about?"


def test_prefer_session_matching_sources_keeps_week_one_among_selected():
    """Week 1 questions must not retrieve Week 9/10 merely because they are selected."""
    week1 = RetrievalSource(
        source_id="week-1",
        label="S1",
        title="Week 1 Introduction to innovation v3.pdf",
        text="Innovation-driven economy",
        object_key="course/lectureNotes/Week 1 Introduction to innovation v3.pdf",
        virtual_course_source=True,
    )
    week10 = RetrievalSource(
        source_id="week-10",
        label="S2",
        title="Week 10 Storytelling.pdf",
        text="Storytelling and course schedule",
        object_key="course/lectureNotes/Week 10 Storytelling.pdf",
        virtual_course_source=True,
    )
    matched = prefer_session_matching_sources(
        (week1, week10),
        "what does week 1 material cover",
    )
    assert [source.source_id for source in matched] == ["week-1"]


def test_prefer_session_matching_sources_fail_open_when_no_title_match():
    """Unmatched session cues keep the selected set; they never search unselected files."""
    week10 = RetrievalSource(
        source_id="week-10",
        label="S1",
        title="Week 10 Storytelling.pdf",
        text="Storytelling",
        object_key="course/lectureNotes/Week 10 Storytelling.pdf",
        virtual_course_source=True,
    )
    matched = prefer_session_matching_sources(
        (week10,),
        "what does week 1 material cover",
    )
    assert [source.source_id for source in matched] == ["week-10"]


def test_local_retriever_lecture_one_prefers_week_one_title():
    """Students say 'lecture 1'; course files are titled Week 1."""
    sources = (
        _source(
            "week-1",
            "S1",
            "Week 1 Introduction to innovation v3.pdf",
            "Introduction to innovation, design thinking, and the course rhythm. " * 20,
        ),
        _source(
            "week-2",
            "S2",
            "Week 2 JTBD Framework Term 1 2026.pdf",
            "Jobs to Be Done, personas, and problem framing for later weeks. " * 20,
        ),
        _source(
            "week-4",
            "S3",
            "Week 4 Affinity Clusters Product Values and Features Oxymoron.pdf",
            "Affinity clusters, product values, and feature oxymorons. " * 20,
        ),
    )
    result = LocalChunkRetriever(max_chunks=3).retrieve(
        RetrievalQuery(
            current_message="what is lecture 1 about",
            current_stage="problem_identification",
            sources=sources,
        )
    )

    assert result.chunks
    assert result.chunks[0].source_id == "week-1"
    assert "Week 1 Introduction to innovation" in result.context
    assert result.chunks[0].source_id != "week-2"


def test_local_retriever_week_one_still_finds_week_one_title():
    sources = (
        _source(
            "week-1",
            "S1",
            "Week 1 Introduction to innovation v3.pdf",
            "Introduction to innovation and the CDE2300 studio. " * 12,
        ),
        _source(
            "week-2",
            "S2",
            "Week 2 JTBD Framework Term 1 2026.pdf",
            "Jobs to Be Done interviews and persona sketches. " * 12,
        ),
    )
    result = LocalChunkRetriever(max_chunks=2).retrieve(
        RetrievalQuery(
            current_message="what is week 1 about",
            current_stage="problem_identification",
            sources=sources,
        )
    )

    assert result.chunks[0].source_id == "week-1"


def test_local_retriever_generic_query_uses_bounded_representative_fallback():
    sources = tuple(
        _source(
            f"source-{index}",
            f"S{index}",
            f"Document {index}",
            (f"Distinct document {index} content. " * 100),
        )
        for index in range(1, 5)
    )
    result = LocalChunkRetriever(
        chunk_chars=500,
        overlap_chars=50,
        max_chunks=2,
        max_chunks_per_source=1,
        max_context_chars=1_500,
    ).retrieve(
        RetrievalQuery(
            current_message="What do these say?",
            current_stage="problem_identification",
            sources=sources,
        )
    )

    assert len(result.chunks) == 2
    assert len({chunk.source_id for chunk in result.chunks}) == 2
    assert len(result.context) <= 1_500


def test_retrieval_source_normalization_keeps_course_group_and_image_label():
    sources = retrieval_sources_from_notebook(
        [
            {
                "id": "lecture",
                "title": "Week 2",
                "kind": "file",
                "extractedText": "Evaluation methods",
                "object_key": "course/lectureNotes/week2.pdf",
                "metadata": {"course_material_group": "Lecture Notes"},
            },
            {
                "id": "diagram",
                "title": "Model.png",
                "kind": "image",
                "extractedText": "",
                "metadata": {},
            },
        ]
    )

    assert sources[0].label == "S1"
    assert sources[0].group == "Lecture Notes"
    assert sources[0].object_key == "course/lectureNotes/week2.pdf"
    assert sources[1].label == "S2"
    assert "Image source" in sources[1].text


_WEEK1_KEY = (
    "course/lectureNotes/Week 1 Introduction to innovation v3.pdf"
)
_WEEK1_TITLE = "Week 1 Introduction to innovation v3.pdf"


def _virtual_week1_record() -> dict[str, object]:
    """Return a shared catalog Week 1 source with empty extracted text."""
    return {
        "id": "virtual-week-1",
        "title": _WEEK1_TITLE,
        "kind": "file",
        "extractedText": "",
        "object_key": _WEEK1_KEY,
        "path": _WEEK1_KEY,
        "metadata": {
            "virtual_course_source": True,
            "shared_course_object": True,
            "course_material_group": "Lecture Notes",
            "object_key": _WEEK1_KEY,
            "course_material_id": course_material_id_from_object_key(_WEEK1_KEY),
        },
    }


def test_virtual_course_source_keeps_empty_retrieval_text():
    sources = retrieval_sources_from_notebook([_virtual_week1_record()])
    assert len(sources) == 1
    assert sources[0].text == ""
    assert sources[0].virtual_course_source is True
    assert sources[0].shared_course_object is True
    assert sources[0].label == "S1"
    assert sources[0].course_material_id == (
        "lecture_week_1_introduction_to_innovation_v3"
    )
    assert UNANALYZABLE_SOURCE_PLACEHOLDER not in sources[0].text


def test_virtual_course_without_kb_does_not_synthesize_placeholder_chunk():
    sources = retrieval_sources_from_notebook([_virtual_week1_record()])
    result = CompositeContextRetriever(
        knowledge_base=None,
        local=LocalChunkRetriever(),
    ).retrieve(
        RetrievalQuery(
            current_message="what are the week 1 contents talking about?",
            current_stage="problem_identification",
            sources=sources,
        )
    )
    assert result.chunks == ()
    assert result.course_retrieval_status == "unavailable"
    assert COURSE_RETRIEVAL_UNAVAILABLE_CONTEXT in result.context
    assert result.failure_category == "config_missing"
    assert UNANALYZABLE_SOURCE_PLACEHOLDER not in result.context
    assert all(
        UNANALYZABLE_SOURCE_PLACEHOLDER not in chunk.text
        for chunk in result.chunks
    )


def test_local_retriever_skips_empty_virtual_course_text():
    source = retrieval_sources_from_notebook([_virtual_week1_record()])[0]
    result = LocalChunkRetriever().retrieve(
        RetrievalQuery(
            current_message="what are the week 1 contents talking about?",
            current_stage="problem_identification",
            sources=(source,),
        )
    )
    assert result.chunks == ()
    assert UNANALYZABLE_SOURCE_PLACEHOLDER not in result.context


def test_week_one_query_expansion_keeps_session_eligible():
    expanded = expand_session_query_text(
        "what are the week 1 contents talking about?"
    )
    assert "lecture 1" in expanded
    week1 = retrieval_sources_from_notebook([_virtual_week1_record()])[0]
    assert "week 1" in week1.title.casefold()


def test_application_virtual_course_gap_is_not_placeholder_evidence(tmp_path):
    store = StudentStore(tmp_path / "virtual-course-gap.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    store.add_source(
        notebook,
        kind="file",
        title=_WEEK1_TITLE,
        mime="application/pdf",
        metadata={
            "virtual_course_source": True,
            "shared_course_object": True,
            "locked_source": True,
            "origin": "lecture_notes_folder",
            "course_material_group": "Lecture Notes",
            "object_key": _WEEK1_KEY,
            "course_material_id": course_material_id_from_object_key(_WEEK1_KEY),
            "storage_provider": "s3",
        },
    )
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    provider = DeterministicCoachProvider(StageDecision.STAY)
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(provider, transitions),
        LearningProgressService(store, notebooks, transitions),
        retriever=CompositeContextRetriever(
            knowledge_base=None,
            local=LocalChunkRetriever(),
        ),
    )
    turn = service.submit(
        CoachRequest(
            thread_id=notebook,
            student_message="what are the week 1 contents talking about?",
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    assert provider.last_prepared_prompt is None
    assert turn.response_text == QA_EVIDENCE_GAP_RESPONSE
    assert UNANALYZABLE_SOURCE_PLACEHOLDER not in turn.response_text
    assert "[S1]" not in turn.response_text
    assistants = [
        message
        for message in store.get_messages(notebook)
        if message.get("role") == "assistant"
    ]
    assert assistants[-1]["content"] == QA_EVIDENCE_GAP_RESPONSE


def test_application_retrieval_is_selected_notebook_scoped_and_audited(tmp_path):
    store = StudentStore(tmp_path / "retrieval-scope.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    other_notebook = store.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )
    selected = add_text_source(
        store,
        notebook,
        "Selected battery study",
        "Thermal battery evidence reports 18 percent capacity loss.",
    )
    hidden = add_text_source(
        store,
        notebook,
        "Deselected secret",
        "SECRET_DESELECTED_CONTENT about thermal batteries.",
    )
    store.set_source_selected(notebook, hidden["id"], False)
    add_text_source(
        store,
        other_notebook,
        "Other notebook secret",
        "SECRET_OTHER_NOTEBOOK_CONTENT about thermal batteries.",
    )
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    provider = DeterministicCoachProvider(StageDecision.STAY)
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(provider, transitions),
        LearningProgressService(store, notebooks, transitions),
    )

    turn = service.submit(
        CoachRequest(
            thread_id=notebook,
            student_message="What thermal battery evidence is available?",
            current_stage="problem_identification",
            response_detail="short",
        )
    )

    assert provider.last_prepared_prompt is not None
    prompt = provider.last_prepared_prompt.composed_text
    assert "18 percent capacity loss" in prompt
    assert "SECRET_DESELECTED_CONTENT" not in prompt
    assert "SECRET_OTHER_NOTEBOOK_CONTENT" not in prompt
    assistant = store.get_messages(notebook)[-1]
    retrieval_refs = assistant["metadata"]["retrieval_refs"]
    assert retrieval_refs[0]["source_id"] == selected["id"]
    assert retrieval_refs[0]["label"] == "S1"
    assert retrieval_refs[0]["chunk_id"].startswith("S1-C")
    assert (
        "Thermal battery evidence reports 18 percent capacity loss."
        in turn.response_text
    )
    assert "[S1]" in turn.response_text
    assert turn.assessment.citations[0].source_id == selected["id"]
    assert assistant["metadata"]["source_refs"] == [
        {
            "id": selected["id"],
            "label": "S1",
            "title": "Selected battery study",
        }
    ]


def test_citation_preview_uses_retrieved_excerpt_not_document_beginning(
    tmp_path,
):
    store = StudentStore(tmp_path / "retrieved-citation.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(
        store,
        notebook,
        "Battery report",
        ("Unrelated background material. " * 160)
        + "Thermal degradation caused exactly 18 percent capacity loss after 500 cycles.",
    )
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(DeterministicCoachProvider(), transitions),
        LearningProgressService(store, notebooks, transitions),
    )

    turn = service.submit(
        CoachRequest(
            thread_id=notebook,
            student_message="What quantified thermal degradation was reported?",
            current_stage="problem_identification",
            response_detail="short",
        )
    )

    assert len(turn.assessment.citations) == 1
    assert "18 percent capacity loss" in turn.assessment.citations[0].excerpt
    assert "18 percent capacity loss" in turn.response_text
    assert "[S1]" in turn.response_text


def test_project_reasoning_skips_selected_source_retrieval(tmp_path):
    class _CountingRetriever:
        def __init__(self) -> None:
            self.calls = 0

        def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
            del query
            self.calls += 1
            return RetrievalResult(context="", chunks=())

    store = StudentStore(tmp_path / "skip-retriever.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, notebook, "Owned", "Owned selected source content")
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    counting = _CountingRetriever()
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(DeterministicCoachProvider(), transitions),
        LearningProgressService(store, notebooks, transitions),
        retriever=counting,
    )
    service.submit(
        CoachRequest(
            thread_id=notebook,
            student_message="I think option B is stronger.",
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    assert counting.calls == 0


def test_course_question_uses_selected_source_retrieval(tmp_path):
    class _CountingRetriever:
        def __init__(self) -> None:
            self.calls = 0

        def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
            del query
            self.calls += 1
            return RetrievalResult(context="", chunks=())

    store = StudentStore(tmp_path / "use-retriever.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, notebook, "Owned", "Owned selected lecture content")
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    counting = _CountingRetriever()
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(DeterministicCoachProvider(), transitions),
        LearningProgressService(store, notebooks, transitions),
        retriever=counting,
    )
    service.submit(
        CoachRequest(
            thread_id=notebook,
            student_message="What does the selected lecture say about accessibility?",
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    assert counting.calls == 1


def test_private_attachment_question_does_not_broaden_to_course_sources(tmp_path):
    """Current attachment questions retrieve only their private turn evidence."""

    class _CapturingRetriever:
        def __init__(self) -> None:
            self.source_ids: list[str] = []

        def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
            self.source_ids = [source.source_id for source in query.sources]
            return RetrievalResult(context="", chunks=())

    class _CourseKnowledgeBase(_CapturingRetriever):
        pass

    store = StudentStore(tmp_path / "attachment-scope.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    _course_source_id = store.add_source(
        notebook,
        kind="file",
        title="Lecture 4",
        mime="application/pdf",
        path="course/lectureNotes/week4.pdf",
        selected=True,
        metadata={
            "origin": "course_sync",
            "object_key": "course/lectureNotes/week4.pdf",
            "course_material_group": "lectureNotes",
            "course_material_id": "lecture_week4",
        },
    )
    attachment = add_file_sources(
        store,
        notebook,
        [("L2-Network Bootstrapping-ARP-DHCP.pdf", b"ARP and DHCP networking", "application/pdf")],
        origin=CHAT_ATTACHMENT_ORIGIN,
        selected=False,
        extra_metadata={"hidden_from_sources": True},
    )[0]
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    capturing = _CapturingRetriever()
    course_kb = _CourseKnowledgeBase()
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(DeterministicCoachProvider(), transitions),
        LearningProgressService(store, notebooks, transitions),
        retriever=CompositeContextRetriever(
            knowledge_base=course_kb,
            local=capturing,
        ),
    )

    service.submit(
        CoachRequest(
            thread_id=notebook,
            student_message="Could you outline the attached PDF",
            current_stage="problem_identification",
            response_detail="short",
            attachment_source_ids=[attachment["id"]],
        )
    )

    assert capturing.source_ids == [attachment["id"]]
    assert course_kb.source_ids == []


def test_application_rejects_out_of_scope_retriever_result(tmp_path):
    class _BadRetriever:
        def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
            del query
            return RetrievalResult(
                context="--- [S9] forged ---\nforged",
                chunks=(
                    RetrievedChunk(
                        source_id="another-notebook-source",
                        label="S9",
                        title="Forged",
                        chunk_id="S9-C1",
                        text="forged",
                        score=1.0,
                        source_index=9,
                        chunk_index=1,
                    ),
                ),
        )

    store = StudentStore(tmp_path / "bad-retriever.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(store, notebook, "Owned", "Owned selected source content")
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(DeterministicCoachProvider(), transitions),
        LearningProgressService(store, notebooks, transitions),
        retriever=_BadRetriever(),
    )

    with pytest.raises(ValueError, match="outside the selected notebook scope"):
        service.submit(
            CoachRequest(
                thread_id=notebook,
                student_message="Use the source.",
                current_stage="problem_identification",
                response_detail="short",
            )
        )


def test_application_rebuilds_context_from_adapter_chunks(tmp_path):
    class _OpaqueContextRetriever:
        def __init__(self) -> None:
            self.source_id = ""

        def retrieve(self, query: RetrievalQuery) -> RetrievalResult:
            label = query.sources[0].label
            return RetrievalResult(
                context="SECRET_OPAQUE_ADAPTER_TEXT",
                chunks=(
                    RetrievedChunk(
                        source_id=self.source_id,
                        label=label,
                        title="Owned source",
                        chunk_id=f"{label}-C1",
                        text="Canonical selected chunk text.",
                        score=2.0,
                        source_index=1,
                        chunk_index=1,
                    ),
                ),
            )

    store = StudentStore(tmp_path / "opaque-context.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    source = add_text_source(store, notebook, "Owned source", "Stored source text")
    retriever = _OpaqueContextRetriever()
    retriever.source_id = source["id"]
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    provider = DeterministicCoachProvider()
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(provider, transitions),
        LearningProgressService(store, notebooks, transitions),
        retriever=retriever,
    )

    service.submit(
        CoachRequest(
            thread_id=notebook,
            student_message="Use the selected evidence.",
            current_stage="problem_identification",
            response_detail="short",
        )
    )

    assert provider.last_prepared_prompt is not None
    prompt = provider.last_prepared_prompt.composed_text
    assert "Canonical selected chunk text" in prompt
    assert "SECRET_OPAQUE_ADAPTER_TEXT" not in prompt


def test_legacy_development_fallback_uses_same_local_retriever(tmp_path):
    store = StudentStore(tmp_path / "legacy-retrieval.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    add_text_source(
        store,
        notebook,
        "Battery evidence",
        ("Background. " * 220) + "Thermal capacity loss reached 18 percent.",
    )
    add_text_source(
        store,
        notebook,
        "Unrelated crossing note",
        "Signal timing for pedestrians. " * 30,
    )

    stream = StudentChatEngine(store).submit(
        notebook,
        "What thermal capacity loss was reported?",
        ChatOptions(model_id="gpt-5.4-mini"),
    )

    assert "18 percent" in stream.retrieval_context
    assert "Unrelated crossing note" not in stream.retrieval_context
    user = store.get_messages(notebook)[-1]
    assert user["metadata"]["retrieval_refs"][0]["label"] == "S1"


def test_course_material_id_is_stable_from_object_key():
    assert (
        course_material_id_from_object_key("course/lectureNotes/week_02_jtbd.pdf")
        == "lecture_week_02_jtbd"
    )
    assert (
        course_material_id_from_object_key("course/readings/pixar.pdf")
        == "reading_pixar"
    )
    assert (
        course_material_id_from_object_key("course/readings/week1.pdf")
        == "reading_week1"
    )
    assert (
        course_material_id_from_object_key("course/readings/archive/week1.pdf")
        == "reading_archive_week1"
    )
    assert (
        course_material_id_from_object_key("course/readings/myweek1.pdf")
        == "reading_myweek1"
    )
    collisions = course_material_id_collisions(
        [
            "course/readings/week 01.pdf",
            "course/readings/week_01.pdf",
            "course/Readings/WEEK_01.PDF",
            "course/lectureNotes/week1.pdf",
        ]
    )
    assert "reading_week_01" in collisions
    assert "lecture_week1" not in collisions


def test_bounded_retrieval_skips_near_duplicate_chunks_from_the_same_source():
    duplicate = "Older pedestrians need a longer crossing interval at night."
    result = bounded_retrieval_result(
        [
            RetrievedChunk(
                source_id="src-1",
                label="S1",
                title="Lecture",
                chunk_id="S1-KB1",
                text=duplicate,
                score=0.9,
                source_index=1,
                chunk_index=1,
            ),
            RetrievedChunk(
                source_id="src-1",
                label="S1",
                title="Lecture",
                chunk_id="S1-KB2",
                text=duplicate,
                score=0.8,
                source_index=1,
                chunk_index=2,
            ),
            RetrievedChunk(
                source_id="src-1",
                label="S1",
                title="Lecture",
                chunk_id="S1-KB3",
                text="A different excerpt about signal timing and kerb height.",
                score=0.7,
                source_index=1,
                chunk_index=3,
            ),
        ]
    )
    assert [chunk.chunk_id for chunk in result.chunks] == ["S1-KB1", "S1-KB3"]
    assert result.context.count(duplicate) == 1


def test_forged_citation_is_not_persisted(tmp_path):
    store = StudentStore(tmp_path / "forged-citation.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    selected = add_text_source(
        store,
        notebook,
        "Selected battery study",
        "Thermal battery evidence reports 18 percent capacity loss.",
    )

    class ForgedCitationProvider:
        provider_id = "mock"

        def model_id_for(self, request: CoachRequest) -> str:
            del request
            return "deterministic-v1"

        def assess(self, request: CoachRequest) -> ProviderAssessmentResult:
            inner = DeterministicCoachProvider(StageDecision.STAY)
            result = inner.assess(request)
            forged = CitationReference(
                source_id="forged-source",
                label="S99",
                title="Invented source",
                excerpt="This citation was not retrieved.",
            )
            assessment = result.assessment.model_copy(
                update={"citations": [*result.assessment.citations, forged]}
            )
            return ProviderAssessmentResult(
                response_text=f"{result.response_text} See [S99].",
                assessment=assessment,
                research_coding=result.research_coding,
            )

    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(ForgedCitationProvider(), transitions),
        LearningProgressService(store, notebooks, transitions),
    )
    turn = service.submit(
        CoachRequest(
            thread_id=notebook,
            student_message="What thermal battery evidence is available?",
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    assistant = store.get_messages(notebook)[-1]
    source_ids = {item["id"] for item in assistant["metadata"]["source_refs"]}
    labels = {item["label"] for item in assistant["metadata"]["source_refs"]}
    assert selected["id"] in source_ids or "[S1]" in turn.response_text
    assert "S99" not in labels
    assert "forged-source" not in source_ids
    assert all(citation.label != "S99" for citation in turn.assessment.citations)


def test_cross_user_source_id_is_rejected_before_retrieval(tmp_path):
    owner = StudentStore(tmp_path / "owner.sqlite3", identifier="student-a")
    owner_notebook = owner.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )
    owner_source = add_text_source(
        owner, owner_notebook, "Owner notes", "Owner-only crossing evidence."
    )
    stranger = StudentStore(tmp_path / "stranger.sqlite3", identifier="student-b")
    stranger_notebook = stranger.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )
    add_text_source(
        stranger, stranger_notebook, "Stranger notes", "SECRET_STRANGER_SOURCE"
    )
    assert stranger.get_source(owner_notebook, owner_source["id"]) is None
    notebooks = SQLiteNotebookRepository(stranger)
    transitions = SQLitePhaseTransitionRepository(stranger)
    service = CoachApplicationService(
        stranger,
        notebooks,
        CoachWorkflow(DeterministicCoachProvider(StageDecision.STAY), transitions),
        LearningProgressService(stranger, notebooks, transitions),
    )
    with pytest.raises(ValueError, match="unknown"):
        service.submit(
            CoachRequest(
                thread_id=stranger_notebook,
                student_message="Use the other student's source.",
                current_stage="problem_identification",
                response_detail="short",
                source_ids=[owner_source["id"]],
            )
        )
    with pytest.raises(ValueError, match="Notebook not found"):
        service.submit(
            CoachRequest(
                thread_id=owner_notebook,
                student_message="Open someone else's notebook.",
                current_stage="problem_identification",
                response_detail="short",
            )
        )


def test_foreign_image_is_not_supplied_as_coach_input(tmp_path, monkeypatch):
    from backend import source_library

    monkeypatch.setattr(source_library.settings, "files_dir", tmp_path / "files")
    png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\x9cc\xf8\x0f"
        b"\x00\x00\x01\x01\x00\x05\x18\xd8N\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    owner = StudentStore(tmp_path / "img-owner.sqlite3", identifier="student-a")
    owner_notebook = owner.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )
    created = add_file_sources(
        owner,
        owner_notebook,
        [("diagram.png", png, "image/png")],
    )
    stranger = StudentStore(tmp_path / "img-stranger.sqlite3", identifier="student-b")
    stranger_notebook = stranger.create_thread(
        model_id="mock", support_mode="critical-thinking"
    )
    images = image_inputs_for_source_ids(
        stranger,
        stranger_notebook,
        [created[0]["id"]],
    )
    assert images == []
    owned = image_inputs_for_source_ids(
        owner,
        owner_notebook,
        [created[0]["id"]],
    )
    assert len(owned) == 1
    assert owned[0]["source_id"] == created[0]["id"]


def test_research_coding_does_not_advance_stage(tmp_path):
    store = StudentStore(tmp_path / "research-independence.sqlite3")
    notebook = store.create_thread(model_id="mock", support_mode="critical-thinking")
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    service = CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(DeterministicCoachProvider(StageDecision.STAY), transitions),
        LearningProgressService(store, notebooks, transitions),
        auto_advance_stages=True,
    )
    turn = service.submit(
        CoachRequest(
            thread_id=notebook,
            student_message="I compared privacy and fairness before choosing the design.",
            current_stage="problem_identification",
            response_detail="short",
        )
    )
    assert turn.pending_transition is None
    progress = store.get_thread(notebook)["metadata"]["learning_journey"]
    assert progress["current_stage"] == "problem_identification"
    assert turn.assessment.recommendation is StageDecision.STAY
