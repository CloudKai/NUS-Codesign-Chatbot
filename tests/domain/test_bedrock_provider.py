"""Deterministic Bedrock coach-adapter contract tests (no AWS or paid calls)."""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest
from fastapi.testclient import TestClient

from backend.api import create_app
from backend.application import CoachApplicationService
from backend.bedrock_provider import BedrockCoachProvider
from backend.domain import (
    CitationReference,
    ClearCode,
    CoachImageInput,
    CoachRequest,
    EducationalAssessment,
    FacioneBehavior,
    FacioneDimensionScores,
    ProviderCoachOutput,
    ProvisionalResearchCoding,
    ResearchCodingStatus,
    ResearchEvidence,
    StageDecision,
    VALID_STAGE_IDS,
)
from backend.learning_service import LearningProgressService
from backend.mock_provider import DeterministicCoachProvider
from backend.prompts import compose_coach_prompt
from backend.providers import ProviderUnavailableError, configured_coach_provider
from backend.repositories import (
    SQLiteNotebookRepository,
    SQLitePhaseTransitionRepository,
)
from backend.settings import settings
from backend.source_library import add_text_source
from backend.student_store import StudentStore
from backend.workflow import CoachWorkflow

_TINY_PNG = (
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mP8z8BQDwAEhQGAhKmMIQ"
    "AAAABJRU5ErkJggg=="
)
_STUDENT_MESSAGE = "I compared privacy and fairness before choosing the design."
_STAGE_MARKERS = {
    "problem_identification": "STAGE: PROBLEM IDENTIFICATION",
    "concept_generation": "STAGE: CONCEPT GENERATION",
    "design_specification": "STAGE: DESIGN SPECIFICATION",
    "deep_analysis": "STAGE: ETHICS & CRITICAL THINKING",
    "reflection": "STAGE: REFLECTION",
}


class FakeClientError(Exception):
    """Stand-in for botocore ClientError that never imports AWS SDKs."""

    def __init__(self, code: str, message: str = "aws-error") -> None:
        super().__init__(message)
        self.response = {"Error": {"Code": code, "Message": message}}


class FakeBedrockRuntime:
    """Injected bedrock-runtime client that records Converse calls."""

    def __init__(
        self,
        *,
        payload: dict[str, Any] | None = None,
        stop_reason: str = "tool_use",
        error: BaseException | None = None,
        stream_events: list[dict[str, Any]] | None = None,
        stream_error: BaseException | None = None,
        text_payload: str | None = None,
        tool_input: Any = None,
    ) -> None:
        self.converse_calls: list[dict[str, Any]] = []
        self.stream_calls: list[dict[str, Any]] = []
        self._payload = payload
        self._stop_reason = stop_reason
        self._error = error
        self._stream_events = stream_events
        self._stream_error = stream_error
        self._text_payload = text_payload
        self._tool_input = tool_input

    def converse(self, **kwargs: Any) -> dict[str, Any]:
        """Record one Converse invocation and return a fake structured response."""
        self.converse_calls.append(kwargs)
        if self._error is not None:
            raise self._error
        if self._text_payload is not None:
            return {
                "stopReason": self._stop_reason,
                "output": {
                    "message": {
                        "role": "assistant",
                        "content": [{"text": self._text_payload}],
                    }
                },
            }
        tool_input = self._payload if self._tool_input is None else self._tool_input
        content: list[dict[str, Any]] = []
        if tool_input is not None:
            content.append(
                {
                    "toolUse": {
                        "toolUseId": "t1",
                        "name": "coach_turn",
                        "input": tool_input,
                    }
                }
            )
        return {
            "stopReason": self._stop_reason,
            "output": {"message": {"role": "assistant", "content": content}},
        }

    def converse_stream(self, **kwargs: Any) -> dict[str, Any]:
        """Record one ConverseStream invocation and yield fake events."""
        self.stream_calls.append(kwargs)
        if self._stream_error is not None:
            raise self._stream_error
        events = self._stream_events
        if events is None and self._payload is not None:
            events = _tool_stream_events(self._payload, stop_reason=self._stop_reason)
        return {"stream": iter(events or [])}


def _tool_stream_events(
    payload: dict[str, Any], *, stop_reason: str = "tool_use"
) -> list[dict[str, Any]]:
    """Split one tool-input JSON object into ConverseStream events."""
    raw = json.dumps(payload)
    mid = max(1, len(raw) // 2)
    return [
        {
            "contentBlockStart": {
                "start": {"toolUse": {"toolUseId": "t1", "name": "coach_turn"}}
            }
        },
        {"contentBlockDelta": {"delta": {"toolUse": {"input": raw[:mid]}}}},
        {"contentBlockDelta": {"delta": {"toolUse": {"input": raw[mid:]}}}},
        {"contentBlockStop": {}},
        {"messageStop": {"stopReason": stop_reason}},
    ]


def _assessment(
    *,
    stage: str = "problem_identification",
    citations: list[CitationReference] | None = None,
) -> EducationalAssessment:
    """Return a valid coaching assessment for adapter tests."""
    return EducationalAssessment(
        current_stage=stage,
        contribution_summary="The student compared two design constraints.",
        stage_assessment="The contribution is usable but can be developed further.",
        critical_understanding_level="Developing",
        confidence=0.7,
        recommendation=StageDecision.STAY,
        recommendation_rationale="One important element remains to be examined.",
        guidance_questions=["What should you examine next?"],
        learning_summary="The student is developing the design reasoning.",
        citations=citations or [],
        facione_scores=FacioneDimensionScores(analysis=2, evaluation=2),
    )


def _coding(*, quote: str = _STUDENT_MESSAGE) -> ProvisionalResearchCoding:
    """Return valid research coding whose quote matches the test contribution."""
    return ProvisionalResearchCoding(
        coding_status=ResearchCodingStatus.CODED,
        dominant_clear=ClearCode.LOGICAL,
        facione_behaviors=[FacioneBehavior.ANALYSIS, FacioneBehavior.EVALUATION],
        evidence=[
            ResearchEvidence(
                quote=quote,
                rationale="The student explicitly relates constraints to a choice.",
                confidence=0.8,
            )
        ],
    )


def _output(
    *,
    stage: str = "problem_identification",
    research: ProvisionalResearchCoding | None | dict[str, Any] = _coding(),
    citations: list[CitationReference] | None = None,
    response_text: str = "What trade-off still needs evidence [S1]?",
) -> dict[str, Any]:
    """Return a JSON-ready provider envelope, including optional research."""
    envelope = ProviderCoachOutput(
        response_text=response_text,
        assessment=_assessment(stage=stage, citations=citations),
        research_coding=research if not isinstance(research, dict) else None,
    )
    dumped = envelope.model_dump(mode="json")
    if isinstance(research, dict):
        dumped["research_coding"] = research
    return dumped


def _provider(client: FakeBedrockRuntime) -> BedrockCoachProvider:
    """Build the adapter against an injected fake Bedrock client."""
    return BedrockCoachProvider(
        "us.anthropic.claude-test",
        region="us-west-2",
        timeout_seconds=110.0,
        max_retries=0,
        client=client,
    )


def _request(**overrides: Any) -> CoachRequest:
    """Return one minimal coaching request for direct adapter tests."""
    payload = {
        "thread_id": "thread-demo",
        "student_message": _STUDENT_MESSAGE,
        "current_stage": "problem_identification",
        "response_detail": "short",
    }
    payload.update(overrides)
    return CoachRequest(**payload)


def _service(store: StudentStore, provider: BedrockCoachProvider) -> CoachApplicationService:
    """Build the normal application path with the Bedrock adapter injected."""
    notebooks = SQLiteNotebookRepository(store)
    transitions = SQLitePhaseTransitionRepository(store)
    return CoachApplicationService(
        store,
        notebooks,
        CoachWorkflow(provider, transitions),
        LearningProgressService(store, notebooks, transitions),
    )


def test_bedrock_provider_rejects_missing_model_id():
    with pytest.raises(ProviderUnavailableError, match="BEDROCK_MODEL_ID"):
        BedrockCoachProvider("  ", client=FakeBedrockRuntime(payload=_output()))


def test_valid_structured_coaching_and_research_coding():
    client = FakeBedrockRuntime(payload=_output())
    result = _provider(client).assess(_request())
    assert result.response_text.startswith("What trade-off")
    assert result.assessment.current_stage == "problem_identification"
    assert result.research_coding is not None
    assert result.research_coding.coding_status is ResearchCodingStatus.CODED
    assert result.research_coding.dominant_clear is ClearCode.LOGICAL
    assert len(client.converse_calls) == 1
    kwargs = client.converse_calls[0]
    assert kwargs["modelId"] == "us.anthropic.claude-test"
    assert kwargs["toolConfig"]["toolChoice"] == {"tool": {"name": "coach_turn"}}
    assert "RetrieveAndGenerate" not in json.dumps(kwargs)
    prompt = kwargs["messages"][0]["content"][0]["text"]
    assert prompt == compose_coach_prompt(_request()).composed_text
    assert _STAGE_MARKERS["problem_identification"] in prompt


def test_absent_or_invalid_research_coding_is_retained_as_uncoded():
    missing = _provider(FakeBedrockRuntime(payload=_output(research=None))).assess(
        _request()
    )
    assert missing.research_coding is None

    invalid = _provider(
        FakeBedrockRuntime(payload=_output(research={"not": "a-coding"}))
    ).assess(_request())
    assert invalid.research_coding is None
    assert invalid.response_text.startswith("What trade-off")


def test_invalid_coaching_is_rejected_without_persistence(tmp_path):
    store = StudentStore(tmp_path / "bedrock-invalid.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeBedrockRuntime(payload={"response_text": ""})
    with pytest.raises(ProviderUnavailableError, match="malformed"):
        _service(store, _provider(client)).submit(
            _request(thread_id=thread_id)
        )
    assert all(item["role"] != "assistant" for item in store.get_messages(thread_id))
    assert store.list_research_observations(notebook_id=thread_id) == []


def test_persisted_phase_overrides_mismatched_model_phase():
    client = FakeBedrockRuntime(payload=_output(stage="reflection"))
    result = _provider(client).assess(_request(current_stage="concept_generation"))
    assert result.assessment.current_stage == "concept_generation"


def test_unknown_citations_removed_at_application_boundary(tmp_path):
    store = StudentStore(tmp_path / "bedrock-citations.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    source = add_text_source(
        store,
        thread_id,
        "Selected battery study",
        "Thermal battery evidence reports 18 percent capacity loss.",
    )
    unknown = CitationReference(
        source_id="not-a-real-source",
        label="S9",
        title="Injected citation",
        excerpt="should be dropped",
    )
    client = FakeBedrockRuntime(
        payload=_output(
            citations=[unknown],
            response_text="Use the selected finding [S1] rather than an unknown label.",
        )
    )
    turn = _service(store, _provider(client)).submit(
        _request(
            thread_id=thread_id,
            student_message="What does the selected source say about thermal loss?",
        )
    )
    assert [item.source_id for item in turn.assessment.citations] == [source["id"]]
    assert turn.assessment.citations[0].label == "S1"
    assert all(item.source_id != "not-a-real-source" for item in turn.assessment.citations)


def test_image_mapping_and_unsupported_image_failure():
    data_url = f"data:image/png;base64,{_TINY_PNG}"
    client = FakeBedrockRuntime(payload=_output())
    _provider(client).assess(
        _request(
            image_inputs=[
                CoachImageInput(source_id="img-1", mime="image/png", data_url=data_url)
            ]
        )
    )
    content = client.converse_calls[0]["messages"][0]["content"]
    assert content[0]["text"]
    image_block = content[1]["image"]
    assert image_block["format"] == "png"
    assert image_block["source"]["bytes"] == base64.b64decode(_TINY_PNG)
    assert data_url not in json.dumps(client.converse_calls[0], default=str)

    unsupported = FakeBedrockRuntime(payload=_output())
    with pytest.raises(ProviderUnavailableError, match="image type"):
        _provider(unsupported).assess(
            _request(
                image_inputs=[
                    CoachImageInput(
                        source_id="img-svg",
                        mime="image/svg+xml",
                        data_url="data:image/svg+xml;base64,PHN2Zy8+",
                    )
                ]
            )
        )
    assert unsupported.converse_calls == []


@pytest.mark.parametrize(
    "error,match",
    [
        (FakeClientError("ThrottlingException", _STUDENT_MESSAGE), "throttled"),
        (TimeoutError(_STUDENT_MESSAGE), "timed out"),
        (FakeClientError("AccessDeniedException", _STUDENT_MESSAGE), "access was denied"),
        (
            FakeClientError("ResourceNotFoundException", _STUDENT_MESSAGE),
            "model is unavailable",
        ),
    ],
)
def test_bedrock_error_translation_hides_aws_and_student_content(
    error: BaseException, match: str
):
    client = FakeBedrockRuntime(error=error)
    with pytest.raises(ProviderUnavailableError, match=match) as raised:
        _provider(client).assess(_request())
    message = str(raised.value)
    assert _STUDENT_MESSAGE not in message
    assert "aws-error" not in message
    assert "AccessDeniedException" not in message


def test_malformed_event_and_truncated_stream_errors():
    malformed = FakeBedrockRuntime(stream_events=[{"unexpected": True}])
    with pytest.raises(ProviderUnavailableError, match="malformed"):
        _provider(malformed).assess_stream(_request())

    truncated = FakeBedrockRuntime(
        stream_events=[
            {
                "contentBlockStart": {
                    "start": {"toolUse": {"toolUseId": "t1", "name": "coach_turn"}}
                }
            },
            {"contentBlockDelta": {"delta": {"toolUse": {"input": '{"response_text":'}}}},
            {"messageStop": {"stopReason": "max_tokens"}},
        ]
    )
    with pytest.raises(ProviderUnavailableError, match="truncated"):
        _provider(truncated).assess_stream(_request())


def test_markdown_fences_are_not_parsed_as_structured_output():
    fenced = (
        "```json\n"
        + json.dumps(_output())
        + "\n```"
    )
    client = FakeBedrockRuntime(text_payload=fenced, stop_reason="end_turn")
    with pytest.raises(ProviderUnavailableError, match="malformed"):
        _provider(client).assess(_request())


def test_sync_and_stream_return_the_same_final_contract():
    payload = _output()
    sync_client = FakeBedrockRuntime(payload=payload)
    stream_client = FakeBedrockRuntime(payload=payload)
    request = _request()
    sync = _provider(sync_client).assess(request)
    streamed = _provider(stream_client).assess_stream(request)
    assert sync.model_dump(mode="json") == streamed.model_dump(mode="json")
    assert len(sync_client.converse_calls) == 1
    assert sync_client.stream_calls == []
    assert len(stream_client.stream_calls) == 1
    assert stream_client.converse_calls == []


def test_idempotent_retry_and_restart_do_not_duplicate(tmp_path):
    database = tmp_path / "bedrock-idempotent.sqlite3"
    store = StudentStore(database)
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    client = FakeBedrockRuntime(payload=_output())
    provider = _provider(client)
    request = _request(thread_id=thread_id, idempotency_key="bedrock-retry-1")
    first = _service(store, provider).submit(request)
    replay = _service(StudentStore(database), provider).submit(request)
    assert replay.response_text == first.response_text
    assert len(client.converse_calls) == 1
    assistants = [
        item for item in store.get_messages(thread_id) if item["role"] == "assistant"
    ]
    assert len(assistants) == 1
    assert len(store.list_research_observations(notebook_id=thread_id)) == 1


@pytest.mark.parametrize("stage_id", sorted(VALID_STAGE_IDS))
@pytest.mark.parametrize("detail", ["short", "long"])
def test_guide_free_and_five_phase_prompt_parity_with_mock(stage_id: str, detail: str):
    request = _request(current_stage=stage_id, response_detail=detail)
    mock = DeterministicCoachProvider(StageDecision.STAY)
    mock.assess(request)
    client = FakeBedrockRuntime(payload=_output(stage=stage_id))
    _provider(client).assess(request)
    prompt = client.converse_calls[0]["messages"][0]["content"][0]["text"]
    assert mock.last_prepared_prompt is not None
    assert prompt == mock.last_prepared_prompt.composed_text
    assert _STAGE_MARKERS[stage_id] in prompt
    expected_mode = "Free" if detail == "long" else "Guide"
    assert f"Guidance mode: {expected_mode}" in prompt
    for other_id, marker in _STAGE_MARKERS.items():
        if other_id != stage_id:
            assert marker not in mock.last_prepared_prompt.stage_instructions


def test_configured_coach_provider_selects_bedrock(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(settings, "model_provider", "bedrock")
    monkeypatch.setattr(settings, "bedrock_model_id", "us.anthropic.claude-test")
    monkeypatch.setattr(settings, "aws_region", "us-west-2")
    provider = configured_coach_provider()
    assert isinstance(provider, BedrockCoachProvider)
    assert provider.provider_id == "bedrock"
    assert provider.model_id_for(_request()) == "us.anthropic.claude-test"


def test_readiness_requires_bedrock_model_id(tmp_path, monkeypatch: pytest.MonkeyPatch):
    client = TestClient(create_app(StudentStore(tmp_path / "bedrock-ready.sqlite3")))
    monkeypatch.setattr(settings, "model_provider", "bedrock")
    monkeypatch.setattr(settings, "bedrock_model_id", "")
    response = client.get("/api/v1/ready")
    assert response.status_code == 503
    assert "BEDROCK_MODEL_ID" in response.json()["detail"]
