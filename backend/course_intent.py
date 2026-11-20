"""Optional local inference for the pre-generation course retrieval decision."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from threading import Lock
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class CourseIntentClassifier(Protocol):
    """Score whether answering a message requires official course evidence."""

    def score(
        self, message: str, history: Sequence[Mapping[str, Any]], titles: Sequence[str]
    ) -> float | None:
        """Return a course-evidence probability, or None when unavailable."""
        ...


def is_first_student_turn(history: Sequence[Mapping[str, Any]]) -> bool:
    """Return whether the thread has no prior student message, allowing a welcome turn."""
    return not any(turn.get("role") == "user" for turn in history)


class _ChoiceProbabilities(BaseModel):
    course_evidence: float = Field(ge=0, le=1)


class _ChoiceResult(BaseModel):
    probabilities: _ChoiceProbabilities


# Concepts from the CDE2300 lecture and reading catalogue.
_COURSE_TOPICS = (
    "innovation, project team size and deliverables, jobs to be done (JTBD), "
    "job stories, customer interviews, struggling moments, personas, affinity "
    "clusters, product values and features, oxymorons, concept generation, "
    "creative matrices, prioritization, prototypes, metaphors and analogies, "
    "user testing and feedback, affordances, poster design, storytelling and storyboards"
)

_COURSE_CRITERIA = {
    "course_evidence": (
        "The official course explanation of a concept, method, or term, "
        "or a factual answer about class requirements from course materials."
    ),
    "no_course_evidence": (
        "Personal project coaching, app or stage navigation, greetings, "
        "or a question about a private file or an unrelated topic."
    ),
}


def course_intent_state(
    message: str, history: Sequence[Mapping[str, Any]], titles: Sequence[str]
) -> str:
    """Build the same bounded course and turn context for training and inference."""
    recent = [
        str(turn.get("content", turn.get("text", "")))[:220]
        for turn in history[-3:]
        if turn.get("role") == "user"
    ]
    return (
        f"Course topics: {_COURSE_TOPICS}\n"
        f"Course materials: {', '.join(titles)[:800]}\n"
        f"Earlier student messages: {' | '.join(recent)}\n"
        f"Current student message: {message[:1200]}"
    )


def course_intent_questions(*, include_unclear: bool = False) -> dict[str, Any]:
    """Return a fresh typed course-evidence question for a decision model."""
    criteria = dict(_COURSE_CRITERIA)
    if include_unclear:
        criteria["unclear"] = "Too little context to tell what information the student needs."
    return {
        "retrieval": {
            "type": "choice",
            "instructions": "What does the current student message need to be answered?",
            "criteria": criteria,
        }
    }


class LayaCourseIntentClassifier:
    """Load a local Laya encoder once and allow one inference at a time."""

    def __init__(self, checkpoint: Path, *, device: str = "cpu") -> None:
        """Load local weights. An invalid checkpoint or missing package fails startup."""
        checkpoint = checkpoint.expanduser().resolve()
        if not (checkpoint / "model.safetensors").is_file():
            raise ValueError("Laya requires a local checkpoint directory with model.safetensors")
        from laya import Agent

        self._agent = Agent(str(checkpoint), device=device)
        self._inference = Lock()

    def score(
        self, message: str, history: Sequence[Mapping[str, Any]], titles: Sequence[str]
    ) -> float | None:
        """Score bounded turn context locally. A busy classifier abstains."""
        if not self._inference.acquire(blocking=False):
            return None
        try:
            result = self._agent.predict(
                course_intent_state(message, history, titles),
                course_intent_questions(include_unclear=True),
            )
            return _ChoiceResult.model_validate(
                result["answers"]["retrieval"]
            ).probabilities.course_evidence
        finally:
            self._inference.release()


class _LearnerChoice(BaseModel):
    probs: _ChoiceProbabilities
    readout: Literal["engine", "head"]
    abstain: bool = False


def load_vega_reader(checkpoint: Path) -> Any:
    """Open local Vega and backbone weights without pulling models at runtime."""
    checkpoint = checkpoint.expanduser().resolve()
    if not (checkpoint / "vega_config.json").is_file() or not (
        checkpoint / "backbone" / "config.json"
    ).is_file():
        raise ValueError("Vega requires a local checkpoint with its backbone directory")
    from vegaml.learn.reader import Reader

    return Reader.load(str(checkpoint), device="cpu", threads=1, token=False)


def learner_course_score(result: Mapping[str, Any]) -> tuple[float | None, str]:
    """Validate a Learner result and retain its readout and abstention."""
    choice = _LearnerChoice.model_validate(result["answers"]["retrieval"])
    return (None if choice.abstain else choice.probs.course_evidence, choice.readout)


class LayaLearnCourseIntentClassifier:
    """Serve a fixed, locally fitted Learner bundle with one active inference."""

    def __init__(self, checkpoint: Path, bundle: Path) -> None:
        """Load a compatible local bundle without enabling feedback or writing state."""
        bundle = bundle.expanduser()
        if not bundle.is_file():
            raise ValueError("Laya Learn requires a local learner bundle file")
        from laya import Learner

        self._learner = Learner(
            bundle=bundle, reader=load_vega_reader(checkpoint), auto=False, cache=0
        )
        if self._learner.questions != course_intent_questions():
            raise ValueError("Laya Learn bundle does not match the course-evidence question")
        self._inference = Lock()

    def score(
        self, message: str, history: Sequence[Mapping[str, Any]], titles: Sequence[str]
    ) -> float | None:
        """Return a validated score, or abstain when busy or the reader abstains."""
        if not self._inference.acquire(blocking=False):
            return None
        try:
            result = self._learner.decide(course_intent_state(message, history, titles))
            score, _ = learner_course_score(result)
            return score
        finally:
            self._inference.release()
