"""Presentation mapping for the always-visible Deep Review button."""

from __future__ import annotations

from pathlib import Path

from streamlit.testing.v1 import AppTest

from backend.learning.stages import THINKING_STAGES
from ui.panels.studio import deep_review_control_view


def test_locked_view_before_reflection_complete() -> None:
    """Incomplete Thinking Path keeps Start Deep Review disabled."""
    prefix = [stage.id for stage in THINKING_STAGES[:-1]]
    view = deep_review_control_view(prefix, running=False)
    assert view.eligible is False
    assert view.disabled is True
    assert view.button_type == "secondary"
    assert view.caption is not None
    assert "Reflection" in view.caption
    assert view.detail_caption is None
    assert view.status_label is None


def test_unlocked_view_when_all_stages_complete() -> None:
    """Completing every stage including Reflection enables Deep Review."""
    all_ids = [stage.id for stage in THINKING_STAGES]
    view = deep_review_control_view(all_ids, running=False)
    assert view.eligible is True
    assert view.disabled is False
    assert view.button_type == "primary"
    assert view.caption == "Deep Review is ready."
    assert view.detail_caption is not None
    assert "few seconds to a couple of minutes" in view.detail_caption
    assert view.status_label is None


def test_running_disables_button_even_when_eligible() -> None:
    """An in-flight Deep Review keeps the button locked without a progress caption."""
    all_ids = [stage.id for stage in THINKING_STAGES]
    view = deep_review_control_view(all_ids, running=True)
    assert view.eligible is True
    assert view.disabled is True
    assert view.caption is None
    assert view.detail_caption is None
    assert view.status_label is not None
    assert view.status_label.startswith("Running Deep Review")


def test_review_tab_renders_projected_deep_review_feedback() -> None:
    """Completed Deep Review snapshot items appear in Strengths / Areas expanders."""
    from backend.specialists.review_orchestration import (
        DEEP_REVIEW_SNAPSHOT_KEY,
        deep_review_snapshot_payload,
    )
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    thread_id = str(app.session_state["thread_id"])
    store = StudentStore()
    store.add_message(
        thread_id,
        "assistant",
        "Coach reply",
        metadata={
            "assessment": {
                "current_stage": "problem_identification",
                "recommendation": "stay",
                "review_strengths": ["Normal strength"],
                "review_improvements": ["Normal improvement"],
                "learning_summary": "Incremental summary.",
                "stage_assessment": "Incremental stage note.",
                "contribution_summary": "Draft.",
            }
        },
    )
    store.update_thread(
        thread_id,
        metadata={
            DEEP_REVIEW_SNAPSHOT_KEY: deep_review_snapshot_payload(
                conversation_revision=1,
                created_at="2026-08-19T00:00:00+00:00",
                synthesis="Deep Review summary.",
                summary="Deep Review summary.",
                strengths=["Deep strength from Sonnet"],
                areas_to_develop=["Deep improvement from Sonnet"],
                facione_scores={"analysis": 3},
                working_conclusion="Deep working conclusion.",
                readiness_candidate=False,
                readiness_evidence=[],
                missing_requirements=[],
                model_id="global.anthropic.claude-sonnet-4-6",
                reviewed_stage_id="problem_identification",
            )
        },
    )
    app.run()
    assert not app.exception
    rendered = "\n".join(markdown.value or "" for markdown in app.markdown)
    assert "Deep strength from Sonnet" in rendered
    assert "Deep improvement from Sonnet" in rendered
    assert "Normal strength" in rendered
    assert "Normal improvement" in rendered
    assert {expander.label for expander in app.expander} >= {
        "Strengths",
        "Areas for improvement",
        "Problem identification",
    }


def test_deep_review_button_is_full_width_and_grouped_with_caption() -> None:
    """Start Deep Review spans the Review column and sits tight under its caption."""
    studio = Path("ui/panels/studio.py").read_text(encoding="utf-8")
    button = studio.split("clicked = st.button(", 1)[1].split(")", 1)[0]
    assert 'key="start_deep_review"' in button
    assert "use_container_width=True" in button
    assert 'key="deep_review_control"' in studio
    assert "gap=10" in studio
    assert '@st.fragment(run_every="2s")' in studio
    assert "_deep_review_running_thread_id" not in studio
    assert "get_deep_review_job" in studio
    assert "This review reflects the conversation at the start of Deep Review" in studio
    css = Path("ui/assets/styles/20-studio.css").read_text(encoding="utf-8")
    assert ".st-key-deep_review_control" in css
    assert ".st-key-start_deep_review" in css
    assert "width:100% !important" in css
    assert "gap:10px !important" in css
    assert "calc(10px - 1rem)" in css
    disabled_block = css.split(".st-key-start_deep_review button:disabled", 1)[1]
    primary_block = css.split(
        '.st-key-start_deep_review [data-testid="stBaseButton-primary"]:not(:disabled)',
        1,
    )[1].split(".st-key-start_deep_review button:disabled", 1)[0]
    assert "background:var(--cd-subtle)" in disabled_block
    assert "color:var(--cd-muted)" in disabled_block
    assert "background:var(--cd-accent)" in primary_block
    assert "background:var(--cd-subtle)" not in primary_block


def test_running_status_hides_expander_chevron() -> None:
    """Compact Deep Review st.status keeps the spinner and hides the toggle arrow."""
    css = Path("ui/assets/styles/20-studio.css").read_text(encoding="utf-8")
    status_css = css.split(
        '.st-key-deep_review_control [data-testid="stExpander"]', 1
    )[1]
    assert "summary::marker" in status_css
    assert "::-webkit-details-marker" in status_css
    assert "stIconMaterial" in status_css
    assert "display:none !important" in status_css.split("stIconMaterial", 1)[1]

