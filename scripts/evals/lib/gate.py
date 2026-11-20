"""Offline gate adapter: one dataset row in, one ``GateDecision`` out.

A thin adapter over ``backend.coaching.evidence_scope.decide_first_pass_scope``
(imported lazily). It owns no scope rule.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class GateDecision:
    """What the gate would do for one message."""

    retrieve: bool
    course: bool
    student: bool
    classifier_retrieve: bool
    second_chance: bool = False
    # Fields the live model mode copies onto the request it builds. They
    # mirror what ``_prepare_authoritative_turn`` stamps for the same turn.
    expected_mode: str | None = None
    intent: str = ""
    needs_retrieval: bool = False
    scope_cleared: bool = False
    attachment_only: bool = False


def scope_inputs_for_row(
    row: Mapping[str, Any], *, upload_retrieval_enabled: bool = False
) -> Any:
    """Build ``backend.coaching.evidence_scope.ScopeInputs`` from a dataset row.

    The offline eval cannot supply four things production reads, so each is an
    explicit input held at the value the pre-refactor gate assumed:

    * image bytes: every file counts as loaded (``image_bytes_resolved=True``),
      so missing image Q&A never fires;
    * ``force_retrieval``: False (a Deep Review path, not a chat turn);
    * the locked-course flag: False (a row has no course-library source);
    * ``frozen_history``: False, and the course-intent model second chance
      stays outside the gate (see ``evaluate_combined_gate``).

    ``upload_retrieval_enabled`` stays False for the gate itself. The upload
    policy block (``_upload_retrieval_policy``) turns it on to measure the
    opt-in rule.

    Source ids are ``eval-source-N`` then ``eval-attachment-N``, the ids
    ``build_live_request`` stamps. ``is_image`` follows the filename extension,
    the same guess ``eval_upload_entries`` makes.
    """
    from backend.coaching.evidence_scope import ScopeInputs, ScopeSource

    entries = eval_upload_entries(row)
    selected = list(row["selected_sources"])
    attachments = list(row["attachments"])
    sources = []
    for index, (raw, entry) in enumerate(zip([*selected, *attachments], entries)):
        is_attachment = index >= len(selected)
        number = index - len(selected) + 1 if is_attachment else index + 1
        sources.append(
            ScopeSource(
                source_id=f"eval-{'attachment' if is_attachment else 'source'}-{number}",
                title=str(raw.get("title") or ""),
                filename=str(raw.get("filename") or ""),
                is_attachment=is_attachment,
                is_course_library=False,
                is_image=entry["kind"] == "image",
                image_bytes_resolved=True,
            )
        )
    return ScopeInputs(
        message=str(row["message"]),
        current_stage=str(row["stage"]),
        sources=tuple(sources),
        attachment_count=len(attachments),
        interaction_intent=row.get("explicit_mode"),
        force_retrieval=False,
        frozen_history=False,
        upload_retrieval_enabled=upload_retrieval_enabled,
    )


def gate_decision(row: Mapping[str, Any]) -> GateDecision:
    """Run the production first-pass scope rules for one message row.

    A thin adapter: it builds the inputs (``scope_inputs_for_row``), calls
    ``backend.coaching.evidence_scope.decide_first_pass_scope``, the same
    function ``_prepare_authoritative_turn`` calls, and maps the result onto
    ``GateDecision``. Image bytes, forced retrieval and the model-driven
    second-chance retrieval path are held at the values ``scope_inputs_for_row``
    documents.

    The effective decision is 'retrieve' only when a source is searched: the
    course catalog (``include_course_catalog``) or at least one personal file.
    """
    from backend.coaching.evidence_scope import decide_first_pass_scope

    scope = decide_first_pass_scope(scope_inputs_for_row(row))
    return GateDecision(
        retrieve=bool(scope.include_course_catalog or scope.searches_personal_files),
        course=bool(scope.include_course_catalog),
        student=bool(scope.searches_personal_files),
        classifier_retrieve=scope.classifier_retrieve,
        second_chance=scope.second_chance,
        expected_mode=scope.expected_mode,
        intent=scope.classifier_intent,
        needs_retrieval=scope.needs_retrieval,
        scope_cleared=scope.scope_cleared,
        attachment_only=scope.attachment_only,
    )


def eval_upload_entries(row: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Project the row's selected and attached files into source dicts.

    Rows hold only a title and a filename, so ``mime`` is guessed from the
    filename extension (``.png`` is an image).
    """
    import mimetypes

    entries: list[dict[str, Any]] = []
    for entry in [*row["selected_sources"], *row["attachments"]]:
        filename = str(entry.get("filename") or "")
        mime = mimetypes.guess_type(filename)[0] or ""
        entries.append(
            {
                "title": str(entry.get("title") or filename),
                "filename": filename,
                "kind": "image" if mime.startswith("image/") else "file",
                "mime": mime,
            }
        )
    return entries
