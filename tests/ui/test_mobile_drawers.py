"""Deterministic contracts for the responsive Gemini-style mobile shell."""

from __future__ import annotations

import re
from html import escape
from pathlib import Path
from types import SimpleNamespace

import pytest
from streamlit.testing.v1 import AppTest

import ui.workspace as workspace_module


class _SessionState(dict[str, object]):
    """Small attribute-compatible session-state stand-in for pure helpers."""

    def __getattr__(self, name: str) -> object:
        try:
            return self[name]
        except KeyError as error:
            raise AttributeError(name) from error

    def __setattr__(self, name: str, value: object) -> None:
        self[name] = value


def _apply_pending_mobile_panel(
    monkeypatch: pytest.MonkeyPatch,
    **values: object,
) -> _SessionState:
    """Run the compatibility normalizer against an isolated state mapping."""
    state = _SessionState(values)
    monkeypatch.setattr(
        workspace_module,
        "st",
        SimpleNamespace(session_state=state),
    )
    # The legacy ``Chats`` request also updates the desktop collapse preference.
    monkeypatch.setattr(workspace_module, "set_nav_collapsed", lambda _value: None)
    workspace_module._apply_pending_mobile_panel()
    return state


def _rendered_markdown(app: AppTest) -> str:
    """Return all markdown HTML/text exposed by an AppTest run."""
    return "\n".join(item.value or "" for item in app.markdown)


def _button(app: AppTest, key: str):
    """Find a button by stable key with a useful assertion failure."""
    return next(button for button in app.button if button.key == key)


def test_mobile_studio_open_defaults_false_in_session() -> None:
    """The right drawer has an explicit closed default, independent of center view."""
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    assert not app.exception
    assert app.session_state["mobile_studio_open"] is False
    assert app.session_state["mobile_nav_open"] is False


def test_mobile_header_renders_current_title_and_five_controls() -> None:
    """The compact row exposes menu, title, Analytics, New chat, and ⋮."""
    from backend.student_store import StudentStore

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    thread_id = str(app.session_state["thread_id"])
    long_title = "A very long current chat title that must ellipsize on a 390px phone"
    StudentStore().update_thread(thread_id, name=long_title)
    app.run()

    assert not app.exception
    rendered = _rendered_markdown(app)
    assert '<div class="cd-mobile-header-title">' in rendered
    assert escape(long_title) in rendered

    keys = {button.key for button in app.button}
    assert "mobile-nav-menu" in keys
    assert "mobile-analytics" in keys
    assert "mobile-new-chat" in keys
    # The more trigger is a popover, but its stable key is still discoverable
    # from the rendered widget inventory in AppTest.
    assert any(str(key or "").startswith("mobile-chat") for key in keys)


def test_header_drawer_controls_are_mutually_exclusive() -> None:
    """Analytics opens the right drawer; hamburger opens the left drawer."""
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    app.session_state["center_view"] = "library"
    app.session_state["mobile_nav_open"] = False
    app.session_state["mobile_studio_open"] = False
    app.run()
    _button(app, "mobile-analytics").click().run()
    assert not app.exception
    assert app.session_state["mobile_studio_open"] is True
    assert app.session_state["mobile_nav_open"] is False
    assert app.session_state["center_view"] == "library"

    _button(app, "mobile-nav-menu").click().run()
    assert not app.exception
    assert app.session_state["mobile_nav_open"] is True
    assert app.session_state["mobile_studio_open"] is False
    assert app.session_state["center_view"] == "library"


def test_legacy_studio_requests_open_right_drawer_without_replacing_center(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Old Studio panel requests become a right overlay and preserve the view."""
    for values in (
        {
            "mobile_panel": "Chat",
            "center_view": "library",
            "mobile_nav_open": True,
            "mobile_studio_open": False,
            "pending_mobile_panel": "Studio",
        },
        {
            "mobile_panel": "Studio",
            "center_view": "search",
            "mobile_nav_open": False,
            "mobile_studio_open": False,
        },
    ):
        state = _apply_pending_mobile_panel(monkeypatch, **values)
        assert state["center_view"] in {"library", "search"}
        assert state["mobile_studio_open"] is True
        assert state["mobile_nav_open"] is False
        assert state["mobile_panel"] != "Studio"


def test_legacy_drawer_requests_are_mutually_exclusive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Opening either legacy drawer closes the other side."""
    studio_state = _apply_pending_mobile_panel(
        monkeypatch,
        mobile_panel="Chat",
        center_view="chat",
        mobile_nav_open=True,
        mobile_studio_open=False,
        pending_mobile_panel="Studio",
    )
    assert studio_state["mobile_studio_open"] is True
    assert studio_state["mobile_nav_open"] is False

    nav_state = _apply_pending_mobile_panel(
        monkeypatch,
        mobile_panel="Chat",
        center_view="chat",
        mobile_nav_open=False,
        mobile_studio_open=True,
        pending_mobile_panel="Chats",
    )
    assert nav_state["mobile_nav_open"] is True
    assert nav_state["mobile_studio_open"] is False


@pytest.mark.parametrize(
    ("drawer_key", "close_key"),
    [
        ("mobile_nav_open", "mobile-nav-close"),
        ("mobile_studio_open", "mobile-studio-close"),
    ],
)
def test_drawer_close_controls_restore_underlying_chat(
    drawer_key: str,
    close_key: str,
) -> None:
    """Each drawer's close control leaves the center Chat view mounted."""
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    app.session_state["center_view"] = "chat"
    app.session_state["mobile_nav_open"] = False
    app.session_state["mobile_studio_open"] = False
    app.session_state[drawer_key] = True
    app.run()
    assert not app.exception

    _button(app, close_key).click().run()
    assert not app.exception
    assert app.session_state["mobile_nav_open"] is False
    assert app.session_state["mobile_studio_open"] is False
    assert app.session_state["center_view"] == "chat"


def test_shared_backdrop_closes_active_drawer() -> None:
    """A click on the shared dimmer dismisses whichever side is active."""
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    app.session_state["mobile_nav_open"] = True
    app.session_state["mobile_studio_open"] = False
    app.run()
    assert not app.exception
    _button(app, "mobile-drawer-backdrop").click().run()
    assert not app.exception
    assert app.session_state["mobile_nav_open"] is False
    assert app.session_state["mobile_studio_open"] is False


@pytest.mark.parametrize(
    ("button_key", "expected_view"),
    [
        ("nav-search-chats", "search"),
        ("nav-library", "library"),
    ],
)
def test_navigation_destinations_close_both_drawers(
    button_key: str,
    expected_view: str,
) -> None:
    """Search and Library retain their routes while dismissing both overlays."""
    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    app.session_state["mobile_nav_open"] = True
    app.session_state["mobile_studio_open"] = True
    app.run()
    _button(app, button_key).click().run()
    assert not app.exception
    assert app.session_state["center_view"] == expected_view
    assert app.session_state["mobile_nav_open"] is False
    assert app.session_state["mobile_studio_open"] is False


def test_recent_selection_and_new_chat_close_both_drawers() -> None:
    """Chat destinations also close overlays and preserve normal routing."""
    from backend.models import LOCKED_CHAT_MODEL_ID
    from backend.student_store import StudentStore
    from backend.student_support import DEFAULT_SUPPORT_MODE

    app = AppTest.from_file("streamlit_app.py", default_timeout=30).run()
    store = StudentStore()
    selected_id = store.create_thread(
        name="Recent selection target",
        model_id=LOCKED_CHAT_MODEL_ID,
        support_mode=DEFAULT_SUPPORT_MODE,
    )
    app.session_state["mobile_nav_open"] = True
    app.session_state["mobile_studio_open"] = True
    app.run()
    _button(app, f"nav-open-{selected_id}").click().run()
    assert app.session_state["thread_id"] == selected_id
    assert app.session_state["center_view"] == "chat"
    assert app.session_state["mobile_nav_open"] is False
    assert app.session_state["mobile_studio_open"] is False

    # Tapping the already-active chat only dismisses drawers (no thread change).
    app.session_state["mobile_nav_open"] = True
    app.session_state["mobile_studio_open"] = True
    app.run()
    active_before = app.session_state["thread_id"]
    _button(app, f"nav-open-{active_before}").click().run()
    assert app.session_state["thread_id"] == active_before
    assert app.session_state["center_view"] == "chat"
    assert app.session_state["mobile_nav_open"] is False
    assert app.session_state["mobile_studio_open"] is False

    app.session_state["mobile_nav_open"] = True
    app.session_state["mobile_studio_open"] = True
    app.run()
    before_new_chat = app.session_state["thread_id"]
    _button(app, "mobile-new-chat").click().run()
    assert app.session_state["thread_id"] != before_new_chat
    assert app.session_state["center_view"] == "chat"
    assert app.session_state["mobile_nav_open"] is False
    assert app.session_state["mobile_studio_open"] is False


def test_mobile_more_menu_has_only_chat_actions_and_analytics_is_dedicated() -> None:
    """⋮ keeps rename/download/delete; Thinking Path belongs to Analytics."""
    workspace = Path("ui/workspace.py").read_text(encoding="utf-8")
    nav = Path("ui/panels/nav.py").read_text(encoding="utf-8")
    header = workspace.split("def _render_mobile_header", 1)[1].split(
        "def _render_collapsed_rail", 1
    )[0]
    chat_menu = header.split('key="mobile_chat_menu"', 1)[1].split(
        "if overlay_open:", 1
    )[0]
    assert "render_chat_actions_menu" in chat_menu
    assert "Thinking Path" not in chat_menu
    assert 'key="mobile-analytics"' in header
    actions = nav.split("def render_chat_actions_menu", 1)[1].split(
        "def _render_recent_menu", 1
    )[0]
    assert "Rename" in actions
    assert "Chat Setting" in actions
    assert "render_transcript_download_control(" in actions
    assert "store.download_transcript(" not in actions
    assert "Download transcript" in nav.split("def render_transcript_download_control", 1)[1].split(
        "def render_chat_actions_menu", 1
    )[0]
    assert "Delete" in actions
    assert "Thinking Path" not in actions
    assert "clear_transcript_export_cache" in workspace


def test_mobile_drawer_css_contract() -> None:
    """Drawer geometry, stacking, motion, and compact-row constraints stay explicit."""
    css = Path("ui/assets/styles/90-responsive.css").read_text(encoding="utf-8")
    mobile = css.split("@media (max-width:1050px)", 1)[1]
    assert any(f"height:{size}rem" in mobile for size in ("3.25", "3.5", "4"))
    assert "flex:0 0" in mobile
    assert "flex-wrap:nowrap" in mobile
    assert "white-space:nowrap" in mobile
    assert "overflow:hidden" in mobile
    title_match = re.search(r"\.cd-mobile-header-title\s*\{([^}]+)\}", mobile)
    assert title_match is not None
    title_css = title_match.group(1)
    assert "text-overflow:ellipsis" in title_css
    assert "white-space:nowrap" in title_css
    assert "text-align:left" in title_css
    assert "height:2.55rem" in title_css
    assert "min-height:2.55rem" in title_css
    # Menu / Analytics / New chat icons must sit in the geometric button center.
    assert "st-key-mobile_nav_menu div[data-testid=\"stButton\"] button" in mobile
    assert (
        "span[data-has-shortcut]" in mobile
        and "width:100% !important" in mobile
    )
    assert 'st-key-mobile_rename_' in mobile
    assert "right:.5rem" in mobile
    assert "grid-template-columns:minmax(0,1fr) auto" in mobile
    assert "width:min(20.5rem,88vw)" in mobile
    assert any(
        marker in mobile
        for marker in ("mobile_nav_backdrop", "mobile_drawer_backdrop", "mobile-drawer-backdrop")
    )
    # Dimmer keeps an accessible label but must not paint "Close drawer".
    assert "st-key-mobile-drawer-backdrop button p" in css
    assert "font-size:0 !important" in css
    assert "st-key-nav_panel" in mobile
    assert "st-key-studio_panel" in mobile
    assert re.search(r"transform\s*:\s*translateX\(-100%\)", mobile)
    assert re.search(r"transform\s*:\s*translateX\(100%\)", mobile)
    assert re.search(
        r"transition\s*:\s*transform\s+(?:220ms|\.22s)\s+ease(?:-in-out)?",
        mobile,
    )
    assert "z-index:420" in mobile
    assert re.search(r"z-index\s*:\s*4(?:3|4)0", mobile)
    assert "prefers-reduced-motion:reduce" in css
    reduced = css.split("prefers-reduced-motion:reduce", 1)[1]
    assert "transition:none" in reduced.replace(" ", "")
    # Review attention must badge the dedicated Analytics control, never the
    # hamburger that opens Navigation.
    attention = mobile.split("Review attention", 1)[1].split(
        "Mobile chat", 1
    )[0]
    assert "mobile_nav_menu" not in attention
    assert "mobile_analyse" in attention
    # Capture-phase feedback opens/closes immediately while Streamlit's
    # authoritative rerun is still reconciling the drawer markers.
    assert "cd-mobile-nav-optimistic" in mobile
    assert "cd-mobile-studio-optimistic" in mobile
    assert "cd-mobile-drawer-closing" in mobile
    helper = Path("ui/layout/column_resize.py").read_text(encoding="utf-8")
    assert 'doc.addEventListener("click"' in helper
    assert 'doc.addEventListener("pointerdown"' not in helper
    assert "handleOptimisticShellAction" in helper
    assert 'setOptimisticDrawer("nav")' in helper
    assert 'setOptimisticDrawer("studio")' in helper
    assert "closeOptimisticDrawers()" in helper


def test_mobile_column_helper_preserves_drawer_widths() -> None:
    """The resize helper must not overwrite off-canvas widths with 100%."""
    helper = Path("ui/layout/column_resize.py").read_text(encoding="utf-8")
    mobile = helper.split("function setMobile", 1)[1].split(
        "function applyLayout", 1
    )[0]
    assert 'role === "nav" || role === "studio"' in mobile
    assert '"min(20.5rem, 88vw)"' in mobile
    assert "setMobile(column, roles[index])" in helper
