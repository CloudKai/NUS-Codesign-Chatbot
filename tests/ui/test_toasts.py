"""Contracts for parent-owned corner toast dismiss and auto-hide."""

from __future__ import annotations

from pathlib import Path

from ui.toasts import (
    DEFAULT_TOAST_DURATION_MS,
    _CORNER_TOAST_CONTROLLER_JS,
    _CORNER_TOAST_CONTROLLER_VERSION,
    _corner_toast_iframe_html,
    show_corner_toasts,
)


def test_parent_controller_owns_dismiss_click_and_timeouts() -> None:
    """Click and auto-hide must be parent-window functions, not iframe closures."""
    controller = _CORNER_TOAST_CONTROLLER_JS
    assert "win.__cdCornerToasts" in controller
    assert f"const VERSION = {_CORNER_TOAST_CONTROLLER_VERSION};" in controller
    assert 'el.closest(".cd-corner-toast-close")' in controller
    assert 'doc.addEventListener' in controller
    assert '"click"' in controller
    assert "clickInstalled" in controller
    assert "win.setTimeout(function () {" in controller
    assert "win.__cdCornerToasts.dismiss(toast)" in controller
    assert "close.addEventListener" not in controller
    assert "min-width: 2rem" in controller
    assert "min-height: 2rem" in controller


def test_iframe_html_only_boots_parent_controller() -> None:
    """The disposable iframe must not bind dismiss; it only boots and calls show."""
    html = _corner_toast_iframe_html(
        ["Course materials are loading."],
        duration_ms=DEFAULT_TOAST_DURATION_MS,
    )
    assert "Course materials are loading." in html
    assert "createElement(\"script\")" in html
    assert "parentWin.__cdCornerToasts.show(messages, durationMs)" in html
    assert f"parentWin.__cdCornerToasts.version !== {_CORNER_TOAST_CONTROLLER_VERSION}" in html
    assert "boot.textContent" in html
    assert "close.addEventListener" not in html
    assert "const dismiss = (toast)" not in html


def test_show_corner_toasts_injects_parent_controller(monkeypatch) -> None:
    """Successful injection ships the parent boot script at zero iframe size."""
    captured: dict[str, object] = {}

    def fake_html(html: str, **kwargs: object) -> None:
        captured["html"] = html
        captured["kwargs"] = kwargs

    monkeypatch.setattr("ui.toasts.components.html", fake_html)
    show_corner_toasts("Course materials are loading.")
    html = str(captured["html"])
    assert "Course materials are loading." in html
    assert "__cdCornerToasts" in html
    assert captured["kwargs"] == {"height": 0, "width": 0}


def test_show_corner_toasts_skips_blank_messages(monkeypatch) -> None:
    """Whitespace-only bodies must not mount a toast iframe."""
    called: list[int] = []
    monkeypatch.setattr(
        "ui.toasts.components.html",
        lambda *_args, **_kwargs: called.append(1),
    )
    show_corner_toasts("", "  ")
    assert called == []


def test_show_corner_toasts_falls_back_to_st_toast(monkeypatch) -> None:
    """Sandbox or Streamlit injection failures still surface st.toast."""
    shown: list[tuple[str, int]] = []

    def fail_html(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("sandbox")

    monkeypatch.setattr("ui.toasts.components.html", fail_html)
    monkeypatch.setattr(
        "ui.toasts.st.toast",
        lambda message, duration=3: shown.append((str(message), int(duration))),
    )
    show_corner_toasts("Course materials are loading.")
    assert shown == [("Course materials are loading.", 3)]


def test_new_notebook_still_triggers_course_materials_toast() -> None:
    """User-initiated notebooks still pop the one-shot loading toast flag."""
    session = Path("ui/session.py").read_text(encoding="utf-8")
    nav = Path("ui/panels/nav.py").read_text(encoding="utf-8")
    workspace = Path("ui/workspace.py").read_text(encoding="utf-8")
    notebooks = Path("ui/notebooks.py").read_text(encoding="utf-8")
    app = Path("streamlit_app.py").read_text(encoding="utf-8")
    # should_rerun=True path and on_click New chat / Your Notebooks create arm toast.
    assert 'st.session_state.toast_course_materials_loading = True' in session
    new_chat = nav.split("def _on_new_chat", 1)[1].split("\ndef ", 1)[0]
    mobile_new = workspace.split("def _on_mobile_new_chat", 1)[1].split("\ndef ", 1)[0]
    dialog_new = notebooks.split("def _on_dialog_new_notebook", 1)[1].split(
        "\ndef ", 1
    )[0]
    assert "toast_course_materials_loading = True" in new_chat
    assert "toast_course_materials_loading = True" in mobile_new
    assert "toast_course_materials_loading = True" in dialog_new
    assert 'st.session_state.pop("toast_course_materials_loading", False)' in app
    assert 'show_corner_toasts("Course materials are loading.")' in app
