"""First-pass evidence scope: one owner for the retrieve/mode precedence rules.

``decide_first_pass_scope`` decides, for one student turn, which evidence the
first provider call may use (the course catalog, the student's own files, both
or neither), the expected response mode, and the cues that fired. It is a pure
function over plain values. It never reads storage, calls a model, checks
authorization or touches settings. Callers pass in anything they had to read:
image-byte availability, the locked-course flag, ``force_retrieval``, the
upload-retrieval setting and (after their own model call) the course-intent
result.

Callers:

* ``backend/coaching/execution.py`` (``_prepare_authoritative_turn``) builds the
  inputs from the authoritative notebook snapshot, applies the result to its
  snapshot, records telemetry, and runs the Laya model call between the two
  decisions (see ``course_intent_promoted``).
* ``scripts/evals/evaluate_retrieval.py`` (``gate_decision``) builds the same
  inputs from a dataset row, so the offline gate numbers use the production
  rules instead of a copy of them.

The module is import-light on purpose (no ``boto3``, providers, settings or
store). ``tests/domain/test_evidence_scope.py`` walks its imports to keep it so.
"""

from __future__ import annotations

from dataclasses import dataclass, replace

from backend.coaching.mode_policy import (
    ModePolicy,
    is_current_stage_status_request,
    is_private_attachment_question,
    is_stage_progression_request,
    is_terminal_completion_request,
    looks_like_information_request,
    resolve_mode_policy,
)
from backend.coaching.workflow_navigation import workflow_skips_retrieval
from backend.retrieval import is_greeting_or_acknowledgement
from backend.retrieval_gate import INTENT_AMBIGUOUS, classify_retrieval_intent
from backend.specialists.routing import looks_like_course_question

# Cues that mean Bedrock KB should search the official course catalog even
# when Lecture Notes / Readings are not Chat-selected.
_COURSE_CATALOG_RETRIEVAL_CUES = frozenset(
    {
        "conservative_course_question",
        "week_or_session",
        "course_grounding",
        "according_to_source",
        "what_source_says",
        "based_on_source",
        "material_noun",
        "compare_to_source",
        "definitional_question",
    }
)

# Cue names. The first-pass and post-model telemetry names are also the
# ``record_field`` names ``execution.py`` emits for them.
CUE_LECTURE_HELP = "lecture_help"
CUE_PROJECT_COACHING = "project_coaching"
CUE_FORCE_RETRIEVAL = "force_retrieval"
CUE_STAGE_STATUS = "current_stage_status_request"
CUE_STAGE_PROGRESSION = "stage_progression_request"
CUE_WORKFLOW_SKIPS_RETRIEVAL = "workflow_skips_retrieval"
CUE_ATTACHMENT_SCOPED = "attachment_retrieval_scoped"
CUE_MISSING_IMAGE_QA = "missing_image_qa"
CUE_COURSE_CATALOG_PREFIX = "course_catalog:"
CUE_LOCAL_COURSE_INTENT = "local_course_intent_retrieval"
CUE_UPLOAD_POLICY = "upload_retrieval_policy"

# Cues the caller records with ``record_field(name, True)`` before its model
# call (in this order), and those it records after it (in this order).
FIRST_PASS_TELEMETRY_CUES: tuple[str, ...] = (
    CUE_STAGE_STATUS,
    CUE_STAGE_PROGRESSION,
    CUE_WORKFLOW_SKIPS_RETRIEVAL,
    CUE_ATTACHMENT_SCOPED,
)
POST_MODEL_TELEMETRY_CUES: tuple[str, ...] = (
    CUE_LOCAL_COURSE_INTENT,
    CUE_UPLOAD_POLICY,
)


@dataclass(frozen=True)
class ScopeSource:
    """One source in the turn's selected set, as plain values.

    Attributes:
        source_id: Stable id (``eval-source-N`` in the offline eval).
        title: Display title, used by the mode policy's title overlap.
        filename: ``filename`` or ``name`` of the source, used the same way.
        is_attachment: True when the id is one of the turn's attachment ids.
        is_course_library: True for locked Lecture Notes / Readings rows. The
            caller computes it; this module cannot import the store.
        is_image: True for ``kind == "image"`` or an ``image/*`` mime.
        image_bytes_resolved: For an image, whether its bytes loaded. The
            caller reads storage for this.
    """

    source_id: str
    title: str = ""
    filename: str = ""
    is_attachment: bool = False
    is_course_library: bool = False
    is_image: bool = False
    image_bytes_resolved: bool = True


@dataclass(frozen=True)
class ScopeInputs:
    """Everything the first-pass scope decision reads.

    Attributes:
        message: Current student message.
        current_stage: Authoritative Thinking Path stage id.
        sources: The turn's selected sources before any scoping, attachments
            included.
        attachment_count: Number of attachment ids on the request.
        interaction_intent: ``"lecture_help"``, ``"project_coaching"`` or None.
        force_retrieval: True for the Deep Review paths that always retrieve.
        frozen_history: True when the turn replays a frozen Deep Review
            history revision.
        upload_retrieval_enabled: ``FAST_CHAT_UPLOAD_RETRIEVAL_ENABLED``,
            read by the caller.
    """

    message: str
    current_stage: str
    sources: tuple[ScopeSource, ...] = ()
    attachment_count: int = 0
    interaction_intent: str | None = None
    force_retrieval: bool = False
    frozen_history: bool = False
    upload_retrieval_enabled: bool = False


@dataclass(frozen=True)
class ScopeDecision:
    """The first-pass scope, mode and cues for one turn.

    Attributes:
        mode_policy: Final mode policy after Lecture Help, scope clearing and
            the course-intent promotion. ``mode_policy.intent`` is what the
            request stamps.
        classifier_retrieve: Raw ``resolve_mode_policy`` retrieve flag.
        classifier_intent: Raw ``resolve_mode_policy`` intent.
        expected_mode: Request stamp: ``"qa"`` for missing image Q&A, else
            ``mode_policy.expected_mode``.
        needs_retrieval: Final retrieval decision (``retrieval_required``).
        include_course_catalog: Search the course catalog (Knowledge Base).
        searches_personal_files: Search the student's own kept files.
        scope_cleared: Stage status, progression or workflow guidance removed
            the evidence scope.
        attachment_only: A private-attachment question narrowed the scope.
        missing_image_qa: Only images are selected and none could be loaded.
        evidence_scoped: A gate override fixed the scope, so the
            ``needs_sources`` second chance and the upload policy stay off.
        kept_source_ids: Effective source ids (before unresolved images are
            dropped from the snapshot).
        unresolved_image_ids: Kept images whose bytes did not load.
        upload_policy_only: The local student-upload search fires on a gate skip.
        course_intent_eligible: A local course-intent classifier may be asked.
            The caller still needs a classifier and course titles.
        course_intent_promoted: The promotion was applied in this decision.
        second_chance: With the setting on, nothing searched and no override
            fixed the scope, so the first call may report ``needs_sources``.
        cues: Cues in the order the rules fired.
    """

    mode_policy: ModePolicy
    classifier_retrieve: bool
    classifier_intent: str
    expected_mode: str | None
    needs_retrieval: bool
    include_course_catalog: bool
    searches_personal_files: bool
    scope_cleared: bool
    attachment_only: bool
    missing_image_qa: bool
    evidence_scoped: bool
    kept_source_ids: tuple[str, ...]
    unresolved_image_ids: frozenset[str]
    upload_policy_only: bool
    course_intent_eligible: bool
    course_intent_promoted: bool
    second_chance: bool
    cues: tuple[str, ...]


def is_image_source(*, kind: str, mime: str) -> bool:
    """Return whether a source's evidence is an image, not extracted text."""
    return str(kind or "").lower() == "image" or str(mime or "").lower().startswith(
        "image/"
    )


def is_searchable_student_upload(*, is_course_library: bool, is_image: bool) -> bool:
    """Return whether local text retrieval can search this source.

    Course library rows are searched only through the Knowledge Base. Images
    reach the model as image input, not as retrieved text.
    """
    return not is_course_library and not is_image


def course_catalog_cues(student_message: str) -> tuple[str, ...]:
    """Return the cues that make a message a course-catalog question.

    ``("course_question",)`` when the specialist router calls it a course
    question, otherwise the retrieval-gate cues that are in the course
    catalog set (none when the gate does not retrieve).
    """
    if looks_like_course_question(student_message):
        return ("course_question",)
    classification = classify_retrieval_intent(
        student_message,
        has_selected_sources=False,
    )
    if not classification.retrieve:
        return ()
    return tuple(
        cue for cue in classification.cues if cue in _COURSE_CATALOG_RETRIEVAL_CUES
    )


def wants_course_catalog_retrieval(
    student_message: str,
    *,
    mode_retrieve: bool,
) -> bool:
    """Return whether this turn should Retrieve against the course library.

    Course library items are view-only in Sources. Genuine course questions
    still need Bedrock KB over the official catalog, decided by intent cues
    rather than Sources selection or title overlap.

    Args:
        student_message: Current student contribution.
        mode_retrieve: Effective mode-policy retrieve flag after workflow
            and attachment overrides.

    Returns:
        True when the Knowledge Base course catalog should be included in
        ``retrieval_sources``.
    """
    return bool(mode_retrieve) and bool(course_catalog_cues(student_message))


def wants_source_need_check(
    *,
    enabled: bool,
    searched: bool,
    evidence_scoped: bool,
) -> bool:
    """Return whether the first Fast Chat call may report ``needs_sources``.

    The check is a second chance for turns the regex gate did not retrieve
    for. It is off unless the setting is on, and it never applies when this
    turn already searched a source or when the application deliberately
    scoped evidence away (stage status, stage navigation, meta-guidance,
    private-attachment scope, forced or lecture-help retrieval, missing image
    bytes).

    Args:
        enabled: ``FAST_CHAT_NEEDS_SOURCES_ENABLED``.
        searched: True when the first pass searched at least one source.
        evidence_scoped: True when the turn's evidence scope is fixed by a
            gate override and a fallback retrieve must not widen it.

    Returns:
        True when the prompt should ask for ``needs_sources`` and the
        application may honour it.
    """
    return bool(enabled) and not searched and not evidence_scoped


def is_bare_lecture_greeting(message: str, *, attachment_count: int) -> bool:
    """Identify a greeting with no question, contribution, or attached file."""
    return not attachment_count and " ".join(message.casefold().split()).rstrip("!.") in {
        "hi", "hello", "hey", "hi there", "hello there", "hey there",
        "good morning", "good afternoon", "good evening",
    }


def is_chit_chat(student_message: str) -> bool:
    """Return whether the turn is a bare greeting or acknowledgement.

    Reuses existing signals only: :func:`is_greeting_or_acknowledgement`
    (the acknowledgement set and greeting prefix that recent-message
    grounding already uses) and :func:`looks_like_information_request`, so
    ``hi, what does my survey say?`` is not chit-chat. Known limit: short
    replies outside that set (``thx``, ``haha nice``, ``ok will try``) are
    not chit-chat.
    """
    return is_greeting_or_acknowledgement(
        student_message
    ) and not looks_like_information_request(student_message)


def local_course_intent_candidate(
    message: str, *, intent: str, evidence_scoped: bool, searched: bool
) -> bool:
    """Allow local classification only on ambiguous turns with no evidence route."""
    return (
        intent == INTENT_AMBIGUOUS
        and not evidence_scoped
        and not searched
        and not is_chit_chat(message)
    )


def wants_student_upload_retrieval(
    *,
    enabled: bool,
    needs_retrieval: bool,
    has_student_upload: bool,
    evidence_scoped: bool,
    student_message: str,
) -> bool:
    """Return whether to search the selected student uploads on this turn.

    The upload retrieval policy (``FAST_CHAT_UPLOAD_RETRIEVAL_ENABLED``) ranks
    excerpts locally, with no Bedrock or Knowledge Base call; loading the
    uploads can still read object storage (one S3 GET per selected upload on a
    chunk-cache miss, or every turn on the extracted-text fallback). It
    applies only when the regex gate chose
    not to retrieve, a non-image student upload is still in scope, no gate
    override fixed the evidence scope (stage status, stage navigation,
    meta-guidance, forced or lecture-help retrieval), and the turn is not
    chit-chat. It never adds the course Knowledge Base.

    Args:
        enabled: ``FAST_CHAT_UPLOAD_RETRIEVAL_ENABLED``.
        needs_retrieval: The gate's decision after its overrides.
        has_student_upload: True when a searchable student upload is among the
            turn's selected sources.
        evidence_scoped: True when a gate override fixed the evidence scope.
        student_message: Current student contribution. Not logged.

    Returns:
        True when the turn should run the local student-upload search.
    """
    return (
        bool(enabled)
        and not needs_retrieval
        and bool(has_student_upload)
        and not evidence_scoped
        and not is_chit_chat(student_message)
    )


def decide_first_pass_scope(
    inputs: ScopeInputs, *, course_intent_promoted: bool = False
) -> ScopeDecision:
    """Decide the first-pass evidence scope, mode and cues for one turn.

    Precedence, in the order the rules run: the mode policy, Lecture Help
    (which wins over every navigation override) or Project Coaching, current
    stage status, Thinking Path progression or workflow guidance (both clear
    the scope), an attachment-only question (narrows to the attachments, even
    after a clear), missing image Q&A, ``force_retrieval``, the course
    catalog, the local course-intent promotion, and last the upload retrieval
    policy.

    The course-intent model call cannot live here. Call this once with the
    default; when ``course_intent_eligible`` is True and the caller's own
    classifier scores at or above its cutoff, call again with
    ``course_intent_promoted=True`` (and ``upload_retrieval_enabled`` re-read
    after the model call). The promotion is applied before the upload rule, and
    only when the turn was eligible.

    Args:
        inputs: Plain values for this turn.
        course_intent_promoted: The caller's classifier asked for the course
            catalog.

    Returns:
        The decision. Telemetry is the caller's job: it records the cues named
        in ``FIRST_PASS_TELEMETRY_CUES`` and ``POST_MODEL_TELEMETRY_CUES``.
    """
    message = inputs.message
    stage = inputs.current_stage
    sources = inputs.sources
    cues: list[str] = []

    policy = resolve_mode_policy(
        message,
        selected_source_titles=[source.title for source in sources],
        selected_source_filenames=[source.filename for source in sources],
        has_selected_sources=bool(sources),
    )
    classifier_retrieve = bool(policy.retrieve)
    classifier_intent = str(policy.intent or "")

    lecture_help = inputs.interaction_intent == "lecture_help"
    if lecture_help:
        cues.append(CUE_LECTURE_HELP)
        policy = ModePolicy(
            intent="high_confidence_source",
            expected_mode="qa",
            retrieve=not is_bare_lecture_greeting(message, attachment_count=inputs.attachment_count),
            retrieval_intent=policy.retrieval_intent,
        )
    elif inputs.interaction_intent == "project_coaching":
        cues.append(CUE_PROJECT_COACHING)
        policy = replace(policy, expected_mode="coaching")

    kept = list(sources)
    images = [source for source in sources if source.is_image]
    unresolved = {
        source.source_id for source in images if not source.image_bytes_resolved
    }

    stage_status_request = not lecture_help and is_current_stage_status_request(
        message
    )
    if stage_status_request:
        # A current-stage lookup is sourced exclusively from the notebook
        # journey: no evidence scope at all.
        policy = ModePolicy(
            intent=policy.intent,
            expected_mode="qa",
            retrieve=False,
            retrieval_intent=policy.retrieval_intent,
            mixed=policy.mixed,
        )
        kept, images, unresolved = [], [], set()
        cues.append(CUE_STAGE_STATUS)
    progression_request = not lecture_help and (
        is_stage_progression_request(message)
        or is_terminal_completion_request(message, current_stage=stage)
    )
    workflow_no_retrieve = not lecture_help and workflow_skips_retrieval(
        message, current_stage=stage
    )
    if progression_request or (workflow_no_retrieve and not stage_status_request):
        # Stage navigation, meta-guidance, prior-stage review and compound
        # status+guidance must not be hijacked by selected source titles.
        policy = ModePolicy(
            intent=policy.intent,
            expected_mode="coaching",
            retrieve=False,
            retrieval_intent=policy.retrieval_intent,
            mixed=policy.mixed,
        )
        if progression_request:
            cues.append(CUE_STAGE_PROGRESSION)
        elif workflow_no_retrieve:
            cues.append(CUE_WORKFLOW_SKIPS_RETRIEVAL)
        kept, images, unresolved = [], [], set()
    scope_cleared = bool(
        stage_status_request
        or progression_request
        or workflow_no_retrieve
    )

    attachment_only = is_private_attachment_question(
        message, attachment_count=inputs.attachment_count
    )
    if attachment_only:
        kept = [source for source in kept if source.is_attachment]
        images = [source for source in images if source.is_attachment]
        unresolved = {
            source.source_id for source in images if not source.image_bytes_resolved
        }

    # The effective ids are frozen before unresolved image rows are dropped:
    # a missing selected image is an evidence gap, not leave to use model
    # knowledge.
    kept_source_ids = tuple(source.source_id for source in kept if source.source_id)
    missing_image_qa = bool(images) and (
        len(images) == len(sources)
        and not any(source.image_bytes_resolved for source in images)
        and looks_like_information_request(message)
    )
    if missing_image_qa:
        cues.append(CUE_MISSING_IMAGE_QA)

    needs_retrieval = bool(policy.retrieve)
    if attachment_only:
        needs_retrieval = True
        cues.append(CUE_ATTACHMENT_SCOPED)
    if missing_image_qa:
        needs_retrieval = True
    if inputs.force_retrieval and sources:
        needs_retrieval = True
        cues.append(CUE_FORCE_RETRIEVAL)
    catalog_cues: tuple[str, ...] = ()
    include_course_catalog = (
        needs_retrieval
        and not attachment_only
        and not stage_status_request
        and not progression_request
        and not (workflow_no_retrieve and not stage_status_request)
    )
    if include_course_catalog:
        if lecture_help:
            catalog_cues = (CUE_LECTURE_HELP,)
        elif policy.retrieve or inputs.force_retrieval:
            catalog_cues = course_catalog_cues(message)
        include_course_catalog = bool(catalog_cues)
    if include_course_catalog:
        needs_retrieval = True
        cues.extend(f"{CUE_COURSE_CATALOG_PREFIX}{cue}" for cue in catalog_cues)

    evidence_scoped = bool(
        lecture_help
        or inputs.force_retrieval
        or stage_status_request
        or progression_request
        or workflow_no_retrieve
        or attachment_only
        or missing_image_qa
    )
    course_intent_eligible = local_course_intent_candidate(
        message,
        intent=policy.intent,
        evidence_scoped=bool(
            evidence_scoped
            or kept_source_ids
            or inputs.interaction_intent
            or inputs.frozen_history
        ),
        searched=include_course_catalog,
    )
    promoted = bool(course_intent_promoted and course_intent_eligible)
    if promoted:
        include_course_catalog = needs_retrieval = True
        policy = replace(policy, expected_mode="qa", retrieve=True)
        cues.append(CUE_LOCAL_COURSE_INTENT)

    # Unresolved image rows leave the snapshot; they are images, so they were
    # never searchable uploads or personal files.
    usable = [source for source in kept if source.source_id not in unresolved]
    upload_policy_only = wants_student_upload_retrieval(
        enabled=inputs.upload_retrieval_enabled,
        needs_retrieval=needs_retrieval,
        has_student_upload=any(
            is_searchable_student_upload(
                is_course_library=source.is_course_library, is_image=source.is_image
            )
            for source in usable
        ),
        evidence_scoped=evidence_scoped,
        student_message=message,
    )
    if upload_policy_only:
        needs_retrieval = True
        cues.append(CUE_UPLOAD_POLICY)

    searches_personal_files = needs_retrieval and any(
        not source.is_course_library for source in usable
    )
    return ScopeDecision(
        mode_policy=policy,
        classifier_retrieve=classifier_retrieve,
        classifier_intent=classifier_intent,
        expected_mode="qa" if missing_image_qa else policy.expected_mode,
        needs_retrieval=bool(needs_retrieval),
        include_course_catalog=bool(include_course_catalog),
        searches_personal_files=bool(searches_personal_files),
        scope_cleared=scope_cleared,
        attachment_only=bool(attachment_only),
        missing_image_qa=missing_image_qa,
        evidence_scoped=evidence_scoped,
        kept_source_ids=kept_source_ids,
        unresolved_image_ids=frozenset(unresolved),
        upload_policy_only=bool(upload_policy_only),
        course_intent_eligible=bool(course_intent_eligible),
        course_intent_promoted=promoted,
        second_chance=wants_source_need_check(
            enabled=True,
            searched=bool(include_course_catalog or searches_personal_files),
            evidence_scoped=evidence_scoped,
        ),
        cues=tuple(cues),
    )


def scope_label(decision: ScopeDecision) -> str:
    """Name the effective evidence scope with the dataset's scope labels."""
    if decision.include_course_catalog and decision.searches_personal_files:
        return "both"
    if decision.include_course_catalog:
        return "course"
    if decision.searches_personal_files:
        return "student_upload"
    return "none"


__all__ = (
    "CUE_ATTACHMENT_SCOPED",
    "CUE_COURSE_CATALOG_PREFIX",
    "CUE_FORCE_RETRIEVAL",
    "CUE_LECTURE_HELP",
    "CUE_LOCAL_COURSE_INTENT",
    "CUE_MISSING_IMAGE_QA",
    "CUE_PROJECT_COACHING",
    "CUE_STAGE_PROGRESSION",
    "CUE_STAGE_STATUS",
    "CUE_UPLOAD_POLICY",
    "CUE_WORKFLOW_SKIPS_RETRIEVAL",
    "FIRST_PASS_TELEMETRY_CUES",
    "POST_MODEL_TELEMETRY_CUES",
    "ScopeDecision",
    "ScopeInputs",
    "ScopeSource",
    "course_catalog_cues",
    "decide_first_pass_scope",
    "is_chit_chat",
    "is_image_source",
    "is_searchable_student_upload",
    "local_course_intent_candidate",
    "scope_label",
    "wants_course_catalog_retrieval",
    "wants_source_need_check",
    "wants_student_upload_retrieval",
)
