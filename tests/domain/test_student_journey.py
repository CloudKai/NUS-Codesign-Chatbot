import pytest

from backend.student_journey import (
    THINKING_STAGES,
    advanced_stage_response,
    concise_coach_response,
    automatic_stage_update,
    complete_and_advance,
    contribution_supports_stage,
    current_stage,
    default_journey,
    journey_progress,
    learning_review,
    mark_stage_completed,
    normalize_journey,
    personalized_stage_questions,
    selectable_stage_ids,
    stage_guidance_questions,
    understanding_level,
)


def test_default_journey_uses_quick_coaching_style():
    journey = default_journey()
    assert journey["response_detail"] == "short"
    assert normalize_journey({})["response_detail"] == "short"
    assert normalize_journey({"response_detail": "long"})["response_detail"] == "long"
    assert normalize_journey({"response_detail": "unknown"})["response_detail"] == "short"


def test_thinking_path_keeps_five_stages_and_ethics_critical_thinking_label():
    assert [stage.id for stage in THINKING_STAGES] == [
        "problem_identification",
        "concept_generation",
        "design_specification",
        "deep_analysis",
        "reflection",
    ]
    assert "ethics_critical" not in {stage.id for stage in THINKING_STAGES}
    ethics = next(stage for stage in THINKING_STAGES if stage.id == "deep_analysis")
    assert ethics.label == "Ethics & Critical Thinking"
    assert ethics.short_label == "Ethics & CT"


def test_journey_advances_through_all_critical_thinking_stages():
    journey = default_journey()
    assert current_stage(journey).id == "problem_identification"
    assert journey_progress(journey) == 0

    for index, stage in enumerate(THINKING_STAGES):
        assert current_stage(journey).id == stage.id
        journey = complete_and_advance(journey, note=f"My {stage.short_label} reflection")
        assert stage.id in journey["completed_stages"]
        assert journey["stage_notes"][stage.id]
        assert journey_progress(journey) == round(
            (index + 1) / len(THINKING_STAGES) * 100
        )

    assert current_stage(journey).id == "reflection"
    assert understanding_level(journey)[0] == "Integrated"


def test_journey_normalization_and_short_long_learning_reviews():
    journey = normalize_journey(
        {
            "current_stage": "reflection",
            "completed_stages": [
                "problem_identification",
                "concept_generation",
                "design_specification",
                "deep_analysis",
            ],
            "stage_notes": {"deep_analysis": "The sample is small."},
            "working_conclusion": "The claim is plausible but still uncertain.",
            "critical_reflection": "I now distinguish correlation from causation.",
            "response_detail": "long",
        }
    )
    messages = [
        {"role": "user", "content": f"Student contribution {index}"}
        for index in range(1, 7)
    ]
    messages.insert(1, {"role": "assistant", "content": "Coaching response"})

    short_review = learning_review(messages, journey, detail="short")
    long_review = learning_review(messages, journey, detail="long")

    assert short_review["current_stage"] == "Reflection"
    assert short_review["understanding_level"] == "Connected"
    assert len(short_review["contributions"]) == 3
    assert len(long_review["contributions"]) == 6
    assert "summarized here" in short_review["summary"]
    assert short_review["facione_scores"] == {
        "analysis": 0,
        "interpretation": 0,
        "inference": 0,
        "evaluation": 0,
        "explanation": 0,
        "self_regulation": 0,
    }
    assert long_review["stage_notes"] == [
        {"stage": "Ethics & Critical Thinking", "note": "The sample is small."}
    ]
    assert "plausible" in long_review["conclusion"]
    assert "correlation" in long_review["critical_reflection"]


def test_selectable_stage_ids_requires_contiguous_validated_completion():
    assert selectable_stage_ids({"current_stage": "problem_identification"}) == (
        "problem_identification",
    )
    assert selectable_stage_ids(
        {
            "current_stage": "problem_identification",
            "completed_stages": ["problem_identification"],
        }
    ) == (
        "problem_identification",
        "concept_generation",
    )
    assert selectable_stage_ids(
        {
            "current_stage": "design_specification",
            "completed_stages": ["problem_identification", "concept_generation"],
        }
    ) == (
        "problem_identification",
        "concept_generation",
        "design_specification",
    )
    assert selectable_stage_ids(
        {
            "current_stage": "problem_identification",
            "completed_stages": [
                "problem_identification",
                "concept_generation",
                "design_specification",
                "deep_analysis",
            ],
        }
    ) == tuple(stage.id for stage in THINKING_STAGES)

    assert selectable_stage_ids(
        {
            "current_stage": "problem_identification",
            "completed_stages": ["problem_identification", "design_specification"],
        }
    ) == ("problem_identification", "concept_generation")


def test_revisiting_completed_stage_preserves_focus_and_unlocked_frontier():
    journey = {
        "current_stage": "problem_identification",
        "completed_stages": [
            "problem_identification",
            "concept_generation",
            "design_specification",
        ],
    }
    normalized = normalize_journey(journey)
    assert normalized["current_stage"] == "problem_identification"
    assert normalized["completed_stages"] == journey["completed_stages"]
    assert selectable_stage_ids(normalized) == (
        "problem_identification",
        "concept_generation",
        "design_specification",
        "deep_analysis",
    )


def test_mark_stage_completed_fails_closed_on_missing_prerequisite():
    with pytest.raises(ValueError, match="prerequisites"):
        mark_stage_completed(
            {
                "current_stage": "design_specification",
                "completed_stages": ["problem_identification"],
            },
            "design_specification",
        )


def test_chat_interaction_automatically_advances_or_keeps_stage():
    journey = default_journey()
    advanced, decision, clean_response = automatic_stage_update(
        journey,
        "My focus is to evaluate whether the study evidence supports the main claim.",
        "That is a clear focus. Let us examine the evidence next. <!-- stage:advance -->",
    )
    assert decision == "advance"
    assert current_stage(advanced).id == "concept_generation"
    assert advanced["completed_stages"] == ["problem_identification"]
    assert "stage:advance" not in clean_response

    stayed, decision, clean_response = automatic_stage_update(
        advanced,
        "I am not sure yet.",
        "Identify one source and explain why it is reliable. <!-- stage:stay -->",
    )
    assert decision == "stay"
    assert current_stage(stayed).id == "concept_generation"
    assert "stage:stay" not in clean_response


def test_stage_assessment_has_a_substantive_fallback():
    assert contribution_supports_stage(
        "The study evidence uses a small sample, so this source may not be reliable.",
        "deep_analysis",
    )
    assert not contribution_supports_stage("Looks good.", "deep_analysis")


def test_each_stage_has_three_guidance_questions():
    for stage in THINKING_STAGES:
        questions = stage_guidance_questions(stage.id)
        assert len(questions) == 3
        assert all(question.endswith("?") for question in questions)


def test_next_stage_questions_personalize_older_adult_topic_and_course_sources():
    questions = personalized_stage_questions(
        "concept_generation",
        "I want to help elderly people cross the road safely.",
        has_course_sources=True,
    )

    assert len(questions) == 2
    assert "Which group of older adults" in questions[0]
    assert "selected lecture notes or readings" in questions[1]


def test_legacy_automatic_transition_renders_as_next_stage_questions():
    display = advanced_stage_response(
        "**Problem identification**\n\nThe problem is clear.\n\n"
        "**Thinking Path:** I’ve moved you to Concepts.",
        "problem_identification",
        "concept_generation",
        ("Which concepts could address this problem?",),
    )

    assert display.startswith(
        "**[Problem identification] -> [Concept generation] Ready**"
    )
    assert "**Questions to explore**" in display
    assert "Which concepts could address this problem?" in display
    assert "I’ve moved you" not in display


def test_legacy_coach_restatement_is_hidden_without_changing_the_response_body():
    display = concise_coach_response(
        "**Problem identification**\n\n"
        "You’re exploring: Helping elderly people cross safely.\n\n"
        "Before moving on, add one concrete detail."
    )

    assert "You’re exploring" not in display
    assert display.startswith("**Problem identification**")
    assert "Before moving on" in display


def test_before_we_move_gatekeeping_is_stripped_after_stage_advance():
    """Transition copy must not keep 'before we move' once the stage advanced."""
    display = concise_coach_response(
        "**[Problem identification] -> [Concept generation] Ready**\n\n"
        "Before we move to Concept Generation, what evidence do you have?\n\n"
        "Let's start with three different concepts."
    )
    assert "Before we move to Concept Generation" not in display
    assert "three different concepts" in display


def test_empty_learning_review_has_a_summary_placeholder():
    review = learning_review([], default_journey())
    assert "summarized here" in review["summary"]
    assert review["has_personalized_assessment"] is False
    assert review["strengths"] == ""
    assert review["improvement_areas"] == []
    assert all(section["items"] == [] for section in review["strength_sections"])
    assert all(section["items"] == [] for section in review["improvement_sections"])
    assert all(score == 0 for score in review["facione_scores"].values())


def test_learning_review_personalizes_from_latest_assessment():
    journey = default_journey()
    messages = [
        {
            "role": "user",
            "content": "I want older adults to cross safely near schools.",
        },
        {
            "role": "assistant",
            "content": "Add one concrete detail.",
            "metadata": {
                "assessment": {
                    "current_stage": "problem_identification",
                    "contribution_summary": "Crossing safety for older adults near schools.",
                    "stage_assessment": (
                        "You named a group and setting, which makes the focus workable."
                    ),
                    "missing_reasoning_elements": [
                        "Name the outcome that would show safer crossings.",
                    ],
                    "critical_understanding_level": "Developing",
                    "recommendation": "stay",
                    "recommendation_rationale": "Add the outcome before moving on.",
                    "guidance_questions": [
                        "What outcome would show the crossing is safer?",
                    ],
                    "learning_summary": (
                        "The student is clarifying a crossing-safety question for "
                        "older adults near schools."
                    ),
                    "working_conclusion": "",
                    "understanding_change": "You are clarifying who and where.",
                    "facione_scores": {
                        "analysis": 3,
                        "interpretation": 2,
                        "inference": 0,
                        "evaluation": 1,
                        "explanation": 0,
                        "self_regulation": 0,
                    },
                }
            },
        },
    ]
    review = learning_review(messages, journey, detail="short")
    assert review["has_personalized_assessment"] is True
    assert review["understanding_level"] == "Developing"
    assert "crossing-safety" in review["summary"]
    assert "I want older adults" not in review["summary"]
    assert review["facione_scores"]["analysis"] == 3
    assert review["facione_scores"]["inference"] == 0
    focus_strengths = next(
        section["items"]
        for section in review["strength_sections"]
        if section["stage_id"] == "problem_identification"
    )
    focus_improvements = next(
        section["items"]
        for section in review["improvement_sections"]
        if section["stage_id"] == "problem_identification"
    )
    assert "group and setting" in focus_strengths[0]
    assert "Crossing safety for older adults" not in " ".join(focus_strengths)
    assert focus_improvements == [
        "Name the outcome that would show safer crossings."
    ]
    assert "clarifying who and where" in review["critical_reflection"]


def test_learning_review_keeps_feedback_by_stage():
    journey = default_journey()
    journey["current_stage"] = "concept_generation"
    journey["completed_stages"] = ["problem_identification"]
    messages = [
        {
            "role": "assistant",
            "content": "Focus reply",
            "metadata": {
                "assessment": {
                    "current_stage": "problem_identification",
                    "recommendation": "advance",
                    "review_strengths": ["Named who is affected."],
                    "review_improvements": ["Clarify the success outcome."],
                    "learning_summary": "Focus clarified.",
                    "stage_assessment": "Focus is workable.",
                    "contribution_summary": "Topic draft.",
                }
            },
        },
        {
            "role": "assistant",
            "content": "Evidence reply",
            "metadata": {
                "assessment": {
                    "current_stage": "concept_generation",
                    "recommendation": "stay",
                    "review_strengths": ["Started checking source quality."],
                    "review_improvements": ["Name one limit of the evidence."],
                    "learning_summary": "Evidence is developing.",
                    "stage_assessment": "Evidence needs a limit.",
                    "contribution_summary": "Evidence draft.",
                }
            },
        },
    ]
    review = learning_review(messages, journey, detail="short")
    by_stage = {
        section["stage_id"]: section["items"]
        for section in review["strength_sections"]
    }
    assert by_stage["problem_identification"] == ["Named who is affected."]
    assert by_stage["concept_generation"] == ["Started checking source quality."]
    assert by_stage["design_specification"] == []
    assert review["improvement_areas"] == ["Name one limit of the evidence."]


def test_learning_review_clamps_invalid_facione_scores():
    journey = default_journey()
    messages = [
        {
            "role": "assistant",
            "content": "Keep going.",
            "metadata": {
                "assessment": {
                    "recommendation": "stay",
                    "learning_summary": "A short overview of progress.",
                    "stage_assessment": "Working on focus.",
                    "contribution_summary": "Topic draft.",
                    "facione_scores": {
                        "analysis": 9,
                        "interpretation": -2,
                        "inference": "oops",
                    },
                }
            },
        }
    ]
    review = learning_review(messages, journey, detail="short")
    assert review["facione_scores"]["analysis"] == 4
    assert review["facione_scores"]["interpretation"] == 0
    assert review["facione_scores"]["inference"] == 0
    assert review["facione_scores"]["evaluation"] == 0


def test_learning_review_projects_only_student_safe_research_facione_fields():
    messages = [
        {
            "role": "user",
            "content": "I compared the options before selecting one.",
        },
        {
            "role": "assistant",
            "metadata": {
                "assessment": {
                    "current_stage": "deep_analysis",
                    "recommendation": "stay",
                    "facione_scores": {"analysis": 3},
                },
                "research_coding": {
                    "coding_status": "coded",
                    "dominant_clear": "logical",
                    "facione_behaviors": ["analysis", "evaluation"],
                    "ethics_concepts": ["fairness"],
                    "holistic_candidate": {"score": 4, "rationale": "Wrong phase"},
                },
            },
        },
        {
            "role": "user",
            "content": "I revised the constraint after testing it.",
        },
        {
            "role": "assistant",
            "metadata": {
                "assessment": {
                    "current_stage": "reflection",
                    "recommendation": "stay",
                    "facione_scores": {"analysis": 1, "self_regulation": 2},
                },
                "research_coding": {
                    "coding_status": "coded",
                    "dominant_clear": "reflective",
                    "facione_behaviors": ["analysis", "self_regulation"],
                    "ethics_concepts": ["responsibility"],
                    "holistic_candidate": {
                        "score": 3,
                        "rationale": "The conversation shows adequate reflective reasoning.",
                        "evidence_spans": [
                            {"start_offset": 0, "end_offset": 42}
                        ],
                    },
                },
            },
        },
    ]

    review = learning_review(messages, default_journey())

    assert review["facione_scores"]["analysis"] == 3
    assert review["facione_behavior_counts"]["analysis"] == 2
    assert review["facione_behavior_counts"]["evaluation"] == 1
    assert review["facione_behavior_counts"]["self_regulation"] == 1
    assert review["facione_holistic_candidate"] == {
        "score": 3,
        "rationale": "The conversation shows adequate reflective reasoning.",
        "evidence_quotes": ["I revised the constraint after testing it."],
    }
    assert "dominant_clear" not in review
    assert "ethics_concepts" not in review
