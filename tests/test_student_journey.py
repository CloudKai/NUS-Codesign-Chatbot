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
    assert "Student contribution 6" in short_review["prompt_summary"]
    assert "Student contribution 1" in long_review["prompt_summary"]
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


def test_empty_learning_review_has_a_prompt_summary_placeholder():
    review = learning_review([], default_journey())
    assert "summarized here" in review["prompt_summary"]
    assert review["has_personalized_assessment"] is False
    assert "meaningful topic" in review["strengths"]
    assert len(review["improvement_areas"]) == 2


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
                    "working_conclusion": "",
                    "understanding_change": "You are clarifying who and where.",
                }
            },
        },
    ]
    review = learning_review(messages, journey, detail="short")
    assert review["has_personalized_assessment"] is True
    assert review["understanding_level"] == "Developing"
    assert "group and setting" in review["strengths"]
    assert "Crossing safety for older adults" in review["strengths"]
    assert review["improvement_areas"] == [
        "Name the outcome that would show safer crossings."
    ]
    assert "clarifying who and where" in review["critical_reflection"]
