"""Turn and evidence state text, choice schemas and the decision reader for Laya heads.

These are the inputs and outputs of the Laya Learn routing and sufficiency heads.
No model is loaded here: ``decide`` takes any object with a ``decide(state)`` method.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from time import perf_counter
from typing import Any

ROUTE_QUESTIONS = {
    "scope": {
        "type": "choice",
        "instructions": "Which evidence does the current turn need?",
        "criteria": {
            "course": "Official course material only, even if an unrelated file is selected.",
            "student_upload": "The selected notebook files only.",
            "both": "Official course material and selected files are both necessary.",
            "none": "The existing conversation or student's own reasoning is enough.",
        },
    },
    "mode": {
        "type": "choice",
        "instructions": "What kind of help is the student asking for?",
        "criteria": {
            "lecture_help": "A direct explanation, lookup, comparison, or factual answer.",
            "project_coaching": "Guidance developing, applying, or testing their design reasoning.",
        },
    },
}


EVIDENCE_QUESTION = {
    "sufficiency": {
        "type": "choice",
        "instructions": "Can the excerpts support an answer to the question?",
        "criteria": {
            "sufficient": "The excerpts support all material parts of the question.",
            "partial": "The excerpts support one part but leave another material part unanswered.",
            "insufficient": "The excerpts do not support an answer to any material part.",
        },
    },
}


def normalized(text: str) -> str:
    """Normalize a message for the exact-overlap check."""
    return " ".join(text.strip(" ?.!").casefold().split())


def route_state(
    message: str,
    history: Sequence[Mapping[str, Any]],
    titles: Sequence[str],
    files: Sequence[Mapping[str, Any]],
) -> str:
    """Format bounded titles, history, and current question without source contents."""
    selected = ", ".join(str(item["title"]) for item in files)[:500]
    recent = [
        f"{turn['role']}: {str(turn.get('text', turn.get('content', '')))[:220]}"
        for turn in history[-4:]
        if turn.get("role") in {"user", "assistant"}
    ]
    return "\n".join(
        [f"Student: {message[:1200]}", f"Selected files: {selected or 'none'}", *recent]
    )


def evidence_state(question: str, excerpts: str) -> str:
    """Format the sufficiency check using only the supplied excerpts."""
    return f"Question: {question[:1200]}\nRetrieved excerpts:\n{excerpts[:8000]}"


def decide(
    model: Any,
    state: str,
    questions: Mapping[str, Any],
) -> tuple[dict[str, str | None], float]:
    """Return validated choice labels or explicit abstentions and elapsed time."""
    started = perf_counter()
    result = model.decide(state)
    elapsed = (perf_counter() - started) * 1000
    choices = {}
    for key, question in questions.items():
        answer = result["answers"][key]
        probabilities = answer["probs"]
        if probabilities.keys() != question["criteria"].keys():
            raise ValueError(f"Unexpected probability labels for {key}")
        choices[key] = None if answer.get("abstain") else max(probabilities, key=probabilities.get)
    return choices, elapsed


def scope_name(course: bool, student: bool) -> str:
    """Translate the existing gate's two search decisions into an evidence scope."""
    if course and student:
        return "both"
    if course:
        return "course"
    return "student_upload" if student else "none"
