"""Presentation mapping for the always-visible Deep Review button."""

from __future__ import annotations

from pathlib import Path

from ui.panels.studio import deep_review_control_view


def test_locked_views_at_zero_one_and_two_turns() -> None:
    """Counters below the interval keep Start Deep Review disabled."""
    for counter in (0, 1, 2):
        view = deep_review_control_view(counter, 3, running=False)
        assert view.eligible is False
        assert view.disabled is True
        assert view.button_type == "secondary"
        assert view.caption == (
            f"Deep Review unlocks after 3 coaching turns — {counter}/3 completed."
        )
        assert view.detail_caption is None
        assert view.status_label is None


def test_unlocked_view_at_interval() -> None:
    """Reaching the persisted interval enables the primary Deep Review button."""
    view = deep_review_control_view(3, 3, running=False)
    assert view.eligible is True
    assert view.disabled is False
    assert view.button_type == "primary"
    assert view.caption == "Deep Review is ready."
    assert view.detail_caption is not None
    assert "few seconds to a couple of minutes" in view.detail_caption
    assert view.status_label is None


def test_unlocked_view_above_interval_does_not_show_a_second_counter() -> None:
    """Surplus qualifying turns still yield one entitlement, not stacked reviews."""
    view = deep_review_control_view(5, 3, running=False)
    assert view.eligible is True
    assert view.disabled is False
    assert view.caption == "Deep Review is ready."
    assert "5/3" not in (view.caption or "")


def test_running_disables_button_even_when_eligible() -> None:
    """An in-flight Deep Review keeps the button locked without a progress caption."""
    view = deep_review_control_view(3, 3, running=True)
    assert view.eligible is True
    assert view.disabled is True
    assert view.caption is None
    assert view.detail_caption is None
    assert view.status_label is not None
    assert view.status_label.startswith("Running Deep Review")


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
