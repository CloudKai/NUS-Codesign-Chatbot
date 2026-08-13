"""Thinking Path journey and Facione review tests."""

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
    normalize_journey,
    personalized_stage_questions,
    stage_guidance_questions,
    understanding_level,
)


def test_journey_advances_through_all_critical_thinking_stages():
    journey = default_journey()
    assert current_stage(journey).id == "focus"
    assert journey_progress(journey) == 0

    for index, stage in enumerate(THINKING_STAGES):
        assert current_stage(journey).id == stage.id
        journey = complete_and_advance(journey, note=f"My {stage.short_label} reflection")
        assert stage.id in journey["completed_stages"]
        assert journey["stage_notes"][stage.id]
        assert journey_progress(journey) == round(
            (index + 1) / len(THINKING_STAGES) * 100
        )

    assert current_stage(journey).id == "conclusion"
    assert understanding_level(journey)[0] == "Integrated"


def test_normalization_preserves_a_completed_stage_being_revisited():
    journey = normalize_journey(
        {
            "current_stage": "focus",
            "completed_stages": ["focus"],
        }
    )

    assert journey["current_stage"] == "focus"
    assert journey["completed_stages"] == ["focus"]


def test_journey_normalization_and_short_long_learning_reviews():
    journey = normalize_journey(
        {
            "current_stage": "synthesis",
            "completed_stages": ["focus", "evidence", "assumptions", "perspectives"],
            "stage_notes": {"evidence": "The sample is small."},
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

    assert short_review["current_stage"] == "Synthesize the reasoning"
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
        {"stage": "Examine evidence", "note": "The sample is small."}
    ]
    assert "plausible" in long_review["conclusion"]
    assert "correlation" in long_review["critical_reflection"]


def test_chat_interaction_automatically_advances_or_keeps_stage():
    journey = default_journey()
    advanced, decision, clean_response = automatic_stage_update(
        journey,
        "My focus is to evaluate whether the study evidence supports the main claim.",
        "That is a clear focus. Let us examine the evidence next. <!-- stage:advance -->",
    )
    assert decision == "advance"
    assert current_stage(advanced).id == "evidence"
    assert advanced["completed_stages"] == ["focus"]
    assert "stage:advance" not in clean_response

    stayed, decision, clean_response = automatic_stage_update(
        advanced,
        "I am not sure yet.",
        "Identify one source and explain why it is reliable. <!-- stage:stay -->",
    )
    assert decision == "stay"
    assert current_stage(stayed).id == "evidence"
    assert "stage:stay" not in clean_response


def test_stage_assessment_has_a_substantive_fallback():
    assert contribution_supports_stage(
        "The study evidence uses a small sample, so this source may not be reliable.",
        "evidence",
    )
    assert not contribution_supports_stage("Looks good.", "evidence")


def test_each_stage_has_three_guidance_questions():
    for stage in THINKING_STAGES:
        questions = stage_guidance_questions(stage.id)
        assert len(questions) == 3
        assert all(question.endswith("?") for question in questions)


def test_next_stage_questions_personalize_older_adult_topic_and_course_sources():
    questions = personalized_stage_questions(
        "evidence",
        "I want to help elderly people cross the road safely.",
        has_course_sources=True,
    )

    assert len(questions) == 2
    assert "Which group of older adults" in questions[0]
    assert "selected lecture notes or readings" in questions[1]


def test_legacy_automatic_transition_renders_as_next_stage_questions():
    display = advanced_stage_response(
        "**Define the focus**\n\nThe focus is clear.\n\n"
        "**Thinking Path:** I’ve moved you to Evidence.",
        "focus",
        "evidence",
        ("Which evidence supports this focus?",),
    )

    assert display.startswith("**Examine evidence**")
    assert "**Questions to explore**" in display
    assert "Which evidence supports this focus?" in display
    assert "I’ve moved you" not in display


def test_legacy_coach_restatement_is_hidden_without_changing_the_response_body():
    display = concise_coach_response(
        "**Define the focus**\n\n"
        "You’re exploring: Helping elderly people cross safely.\n\n"
        "Before moving on, add one concrete detail."
    )

    assert "You’re exploring" not in display
    assert display.startswith("**Define the focus**")
    assert "Before moving on" in display


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
                    "current_stage": "focus",
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
        if section["stage_id"] == "focus"
    )
    focus_improvements = next(
        section["items"]
        for section in review["improvement_sections"]
        if section["stage_id"] == "focus"
    )
    assert "group and setting" in focus_strengths[0]
    assert "Crossing safety for older adults" not in " ".join(focus_strengths)
    assert focus_improvements == [
        "Name the outcome that would show safer crossings."
    ]
    assert "clarifying who and where" in review["critical_reflection"]


def test_learning_review_keeps_feedback_by_stage():
    journey = default_journey()
    journey["current_stage"] = "evidence"
    journey["completed_stages"] = ["focus"]
    messages = [
        {
            "role": "assistant",
            "content": "Focus reply",
            "metadata": {
                "assessment": {
                    "current_stage": "focus",
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
                    "current_stage": "evidence",
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
    assert by_stage["focus"] == ["Named who is affected."]
    assert by_stage["evidence"] == ["Started checking source quality."]
    assert by_stage["assumptions"] == []
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


def test_learning_review_keeps_strongest_facione_evidence_across_turns():
    journey = default_journey()
    messages = [
        {
            "role": "assistant",
            "content": "Earlier assessment.",
            "metadata": {
                "assessment": {
                    "recommendation": "stay",
                    "learning_summary": "Earlier progress.",
                    "facione_scores": {
                        "analysis": 3,
                        "interpretation": 2,
                        "inference": 1,
                        "evaluation": 9,
                    },
                }
            },
        },
        {
            "role": "assistant",
            "content": "Later assessment.",
            "metadata": {
                "assessment": {
                    "recommendation": "stay",
                    "learning_summary": "Later progress.",
                    "facione_scores": {
                        "analysis": 1,
                        "interpretation": 3,
                        "inference": "invalid",
                        "evaluation": 2,
                        "explanation": 2,
                    },
                }
            },
        },
    ]

    review = learning_review(messages, journey)

    assert review["facione_scores"] == {
        "analysis": 3,
        "interpretation": 3,
        "inference": 1,
        "evaluation": 4,
        "explanation": 2,
        "self_regulation": 0,
    }
    assert review["summary"] == "Later progress."


def test_learning_review_separates_quick_and_strict_facione_evidence():
    journey = {
        **default_journey(),
        "response_detail": "long",
        "strict_facione_baseline": {
            "analysis": 2,
            "interpretation": 1,
        },
    }
    messages = [
        {
            "role": "assistant",
            "content": "Quick assessment.",
            "metadata": {
                "coaching_profile": "quick",
                "assessment": {
                    "recommendation": "stay",
                    "learning_summary": "Quick evidence.",
                    "facione_scores": {"analysis": 4, "evaluation": 3},
                },
            },
        },
        {
            "role": "assistant",
            "content": "Strict assessment.",
            "metadata": {
                "coaching_profile": "strict",
                "assessment": {
                    "recommendation": "stay",
                    "learning_summary": "Strict evidence.",
                    "facione_scores": {"analysis": 3, "inference": 2},
                },
            },
        },
    ]

    strict_review = learning_review(messages, journey, detail="long")
    quick_review = learning_review(messages, journey, detail="short")

    assert strict_review["facione_scores"] == {
        "analysis": 3,
        "interpretation": 1,
        "inference": 2,
        "evaluation": 0,
        "explanation": 0,
        "self_regulation": 0,
    }
    assert quick_review["facione_scores"] == {
        "analysis": 4,
        "interpretation": 0,
        "inference": 0,
        "evaluation": 3,
        "explanation": 0,
        "self_regulation": 0,
    }


def test_legacy_facione_assessments_seed_both_profiles_and_baseline_is_clamped():
    journey = normalize_journey(
        {
            **default_journey(),
            "response_detail": "long",
            "strict_facione_baseline": {
                "analysis": 9,
                "interpretation": "invalid",
            },
        }
    )
    messages = [
        {
            "role": "assistant",
            "content": "Legacy assessment.",
            "metadata": {
                "assessment": {
                    "recommendation": "stay",
                    "learning_summary": "Legacy evidence.",
                    "facione_scores": {"evaluation": 2},
                }
            },
        }
    ]

    assert journey["strict_facione_baseline"]["analysis"] == 4
    assert journey["strict_facione_baseline"]["interpretation"] == 0
    assert learning_review(messages, journey, detail="short")["facione_scores"][
        "evaluation"
    ] == 2
    assert learning_review(messages, journey, detail="long")["facione_scores"][
        "evaluation"
    ] == 2


def test_strict_baseline_recomputes_active_evidence_through_capture_boundary():
    journey = normalize_journey(
        {
            **default_journey(),
            "response_detail": "long",
            "strict_facione_baseline": {
                # This snapshot may contain evidence later removed by revision.
                "scores": {"analysis": 4, "evaluation": 3},
                "captured_through": {
                    "created_at": "2026-01-02T00:00:00+00:00",
                    "message_id": "baseline-last",
                },
            },
        }
    )
    messages = [
        {
            "id": "active-legacy",
            "createdAt": "2026-01-01T00:00:00+00:00",
            "role": "assistant",
            "metadata": {
                "assessment": {
                    "recommendation": "stay",
                    "facione_scores": {"analysis": 2},
                }
            },
        },
        {
            "id": "later-quick",
            "createdAt": "2026-01-03T00:00:00+00:00",
            "role": "assistant",
            "metadata": {
                "coaching_profile": "quick",
                "assessment": {
                    "recommendation": "stay",
                    "facione_scores": {"analysis": 4, "evaluation": 4},
                },
            },
        },
        {
            "id": "strict-turn",
            "createdAt": "2026-01-04T00:00:00+00:00",
            "role": "assistant",
            "metadata": {
                "coaching_profile": "strict",
                "assessment": {
                    "recommendation": "stay",
                    "facione_scores": {"inference": 3},
                },
            },
        },
    ]

    scores = learning_review(messages, journey, detail="long")["facione_scores"]

    assert scores["analysis"] == 2
    assert scores["evaluation"] == 0
    assert scores["inference"] == 3


def test_learning_review_ignores_superseded_assessment_branch(tmp_path):
    from backend.student_store import StudentStore

    store = StudentStore(tmp_path / "facione-revision.sqlite3")
    thread_id = store.create_thread(model_id="mock", support_mode="critical-thinking")
    original_user_id = store.add_message(thread_id, "user", "Original prompt")
    store.add_message(
        thread_id,
        "assistant",
        "Original assessment",
        metadata={
            "assessment": {
                "recommendation": "stay",
                "learning_summary": "Original branch.",
                "facione_scores": {"analysis": 4, "evaluation": 4},
            }
        },
    )

    store.revise_user_message(
        thread_id,
        original_user_id,
        "Revised prompt",
        model_id="mock",
        metadata={},
    )
    review = learning_review(store.get_messages(thread_id), default_journey())

    assert review["facione_scores"] == {
        "analysis": 0,
        "interpretation": 0,
        "inference": 0,
        "evaluation": 0,
        "explanation": 0,
        "self_regulation": 0,
    }
