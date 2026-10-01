"""Backward-compatible Thinking Path façade.

The provider-independent implementation lives in :mod:`backend.learning`.
Existing imports remain stable while the domain is split into cohesive modules.
"""

from backend.learning.journey import (
    DEFAULT_RESPONSE_DETAIL,
    FACIONE_DIMENSIONS,
    FACIONE_SCORE_LABELS,
    RESPONSE_DETAILS,
    advanced_stage_response,
    automatic_stage_update,
    complete_and_advance,
    concise_coach_response,
    contribution_supports_stage,
    current_stage,
    default_journey,
    journey_progress,
    learning_review,
    mark_stage_completed,
    next_stage_id,
    normalize_journey,
    personalized_stage_questions,
    selectable_stage_ids,
    selection_pending_move_footer,
    selection_pending_ready_response,
    set_current_stage,
    stage_guidance_questions,
    stage_selection_enabled,
    understanding_level,
)
from backend.learning.stage_briefing import (
    compose_stage_move_briefing,
    stage_move_heading,
)
from backend.learning.stages import (
    DEFAULT_STAGE,
    STAGE_BY_ID,
    THINKING_STAGES,
    ThinkingStage,
)

__all__ = [
    "DEFAULT_RESPONSE_DETAIL",
    "DEFAULT_STAGE",
    "FACIONE_DIMENSIONS",
    "FACIONE_SCORE_LABELS",
    "RESPONSE_DETAILS",
    "STAGE_BY_ID",
    "THINKING_STAGES",
    "ThinkingStage",
    "advanced_stage_response",
    "automatic_stage_update",
    "complete_and_advance",
    "compose_stage_move_briefing",
    "concise_coach_response",
    "contribution_supports_stage",
    "current_stage",
    "default_journey",
    "journey_progress",
    "learning_review",
    "mark_stage_completed",
    "next_stage_id",
    "normalize_journey",
    "personalized_stage_questions",
    "selectable_stage_ids",
    "selection_pending_move_footer",
    "selection_pending_ready_response",
    "set_current_stage",
    "stage_guidance_questions",
    "stage_move_heading",
    "stage_selection_enabled",
    "understanding_level",
]
