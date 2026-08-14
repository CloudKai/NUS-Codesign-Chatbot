"""Profile settings popover for local appearance, language, and help."""

from __future__ import annotations

import json
from html import escape

import streamlit as st
import streamlit.components.v1 as components
from streamlit.errors import StreamlitAPIException

from backend.student_journey import RESPONSE_DETAILS, normalize_journey

from ui.auth_gate import app_logout_url, logout_user
from ui.components import profile_initial
from ui.constants import APPEARANCE_MODES, RESPONSE_LANGUAGES
from ui.menu_popovers import close_menu_popover, menu_popover_widget_key
from ui.runtime import rerun_fragment, store
from ui.session import save_journey
from ui.settings import persist_appearance, persist_response_language


COACHING_STYLE_LABELS = {
    "short": "Quick",
    "long": "Strict",
}
COACHING_STYLE_VALUES = {
    label: detail for detail, label in COACHING_STYLE_LABELS.items()
}


def persist_display_name() -> None:
    """Store the local display name used by the profile shell."""
    cleaned = " ".join(str(st.session_state.profile_display_name or "").split())[:80]
    st.session_state.display_name = cleaned or "Student"
    store.update_thread(
        st.session_state.thread_id,
        metadata={"display_name": st.session_state.display_name},
    )


def _sync_profile_avatar_initial(initial: str) -> None:
    """Update the popover trigger after a fragment-local display-name edit."""
    encoded_initial = json.dumps(initial)
    components.html(
        f"""
<script>
(() => {{
  const button = window.parent.document.querySelector(
    '.st-key-topbar_profile [data-testid="stPopover"] button'
  );
  const label = button?.querySelector('p');
  if (label) {{
    label.textContent = {encoded_initial};
  }}
}})();
</script>
        """,
        height=0,
        width=0,
    )


@st.fragment
def _render_display_name_fragment(display_name: str) -> None:
    """Render display-name editing without redrawing the workspace."""
    st.text_input(
        "Display name",
        value=display_name,
        max_chars=80,
        key="profile_display_name",
        on_change=persist_display_name,
        placeholder="Student",
    )
    current_name = str(st.session_state.get("display_name") or "Student")
    _sync_profile_avatar_initial(profile_initial(current_name))


@st.fragment
def _render_language_fragment() -> None:
    """Render response-language selection without redrawing the workspace."""
    current_language = str(st.session_state.response_language or "English")
    if current_language not in RESPONSE_LANGUAGES:
        current_language = "English"
        st.session_state.response_language = current_language
    st.session_state.setting_response_language = current_language
    _render_language_dropdown(current_language)


def _select_coaching_style(detail: str) -> None:
    """Persist one existing response-detail value from the profile control."""
    journey = normalize_journey(st.session_state.learning_journey)
    if detail != journey["response_detail"]:
        journey["response_detail"] = detail
        save_journey(journey)


def _persist_coaching_style() -> None:
    """Map the student-facing coaching label to the existing journey value."""
    detail = COACHING_STYLE_VALUES.get(
        str(st.session_state.get("setting_coaching_style") or "")
    )
    if detail:
        _select_coaching_style(detail)


@st.fragment
def _render_coaching_style_fragment() -> None:
    """Render response-detail preferences without redrawing the workspace."""
    st.session_state["_topbar_guidance_fragment_runs"] = (
        int(st.session_state.get("_topbar_guidance_fragment_runs") or 0) + 1
    )
    journey = normalize_journey(st.session_state.learning_journey)
    current_detail = journey["response_detail"]
    labels = [COACHING_STYLE_LABELS[detail] for detail in RESPONSE_DETAILS]
    if st.session_state.get("setting_coaching_style") not in labels:
        st.session_state.setting_coaching_style = COACHING_STYLE_LABELS[current_detail]
    st.segmented_control(
        "Coaching style",
        labels,
        key="setting_coaching_style",
        on_change=_persist_coaching_style,
    )


def render_profile_menu() -> None:
    """Render the upper-right profile avatar that opens a compact settings menu."""
    display_name = str(st.session_state.get("display_name") or "Student")
    initial = profile_initial(display_name)
    with st.container(key="topbar_profile"):
        with st.popover(initial):
            with st.container(key="profile_menu_root"):
                st.markdown(
                    '<div class="cd-profile-menu" hidden></div>',
                    unsafe_allow_html=True,
                )
                _render_display_name_fragment(display_name)
                st.segmented_control(
                    "Appearance",
                    APPEARANCE_MODES,
                    key="setting_appearance",
                    # This widget intentionally stays outside a fragment. Its
                    # normal widget rerun must re-execute streamlit_app.py so
                    # the complete theme and layout stylesheet is re-injected.
                    on_change=persist_appearance,
                )
                _render_language_fragment()
                _render_coaching_style_fragment()
                st.divider()
                st.markdown(
                    '<div class="cd-profile-help">'
                    '<div class="cd-profile-help-title">Help</div>'
                    '<div class="cd-profile-help-body">(Will input myself later)</div>'
                    "</div>",
                    unsafe_allow_html=True,
                )
                st.divider()
                # --- Logout (same-tab) ---
                # Prefer a real <a target="_self"> to the local API logout callback.
                # st.link_button opens a new tab; components.html top-navigation is
                # sandboxed and was leaving the authenticated session stuck.
                logout_url = app_logout_url()
                with st.container(key="profile-logout"):
                    if logout_url:
                        st.markdown(
                            '<a class="cd-profile-logout-link" '
                            f'href="{escape(logout_url, quote=True)}" '
                            'target="_self" rel="noopener">Logout</a>',
                            unsafe_allow_html=True,
                        )
                    else:
                        if st.button(
                            "Logout",
                            key="profile-logout-fallback",
                            use_container_width=True,
                            type="secondary",
                        ):
                            logout_user()


def _render_language_dropdown(current_language: str) -> None:
    """Render Language as a select-only menu (no text caret), left-aligned.

    Uses a popover + button pattern so the control cannot be typed into while
    keeping the value left-aligned in the trigger.
    """
    with st.container(key="profile_language"):
        st.markdown(
            '<div class="cd-profile-language-head">'
            '<span class="cd-profile-language-label">Language</span>'
            '<span class="cd-profile-language-help" tabindex="0" '
            'aria-label="The coach responds in this language">'
            "?"
            '<span class="cd-profile-language-tooltip" role="tooltip">'
            "The coach responds in this language"
            "</span>"
            "</span>"
            "</div>",
            unsafe_allow_html=True,
        )
        with st.popover(
            current_language,
            use_container_width=True,
            key=menu_popover_widget_key("profile-language"),
        ):
            for index, language in enumerate(RESPONSE_LANGUAGES):
                if st.button(
                    language,
                    key=f"profile-language-{index}",
                    use_container_width=True,
                    type="tertiary",
                ):
                    if language != current_language:
                        st.session_state.setting_response_language = language
                        persist_response_language()
                    close_menu_popover("profile-language")
                    try:
                        rerun_fragment()
                    except StreamlitAPIException:
                        # Button clicks already rerun this fragment. AppTest
                        # invokes the handler during a full script run, where
                        # scope="fragment" is rejected.
                        pass


def inject_profile_leave_helper() -> None:
    """Install the leave-to-close script outside the avatar layout chain."""
    with st.container(key="profile_leave_helper"):
        _sync_profile_popover_close_on_leave()


def _sync_profile_popover_close_on_leave() -> None:
    """Close the profile menu only after the pointer leaves its chrome.

    Uses mouseenter/mouseleave on the popover body (not document mousemove) so
    widget rerenders and Language portals do not false-close the menu.
    """
    components.html(
        """
<script>
(() => {
  const doc = window.parent.document;
  const win = window.parent;
  const LEAVE_MS = 320;

  if (typeof win.__cdProfileLeaveCleanup === "function") {
    try { win.__cdProfileLeaveCleanup(); } catch (_) {}
  }

  let leaveTimer = null;
  let boundBody = null;
  let boundButton = null;
  let observer = null;

  function profileButton() {
    return doc.querySelector(
      '.st-key-topbar_profile [data-testid="stPopover"] button'
    );
  }

  function profileBody() {
    return doc.querySelector(
      '[data-testid="stPopoverBody"]:has(.st-key-profile_menu_root), ' +
      '[data-testid="stPopoverBody"]:has(.cd-profile-menu), ' +
      '[data-testid="stPopoverBody"]:has(.cd-profile-help)'
    );
  }

  function isOpen() {
    const button = profileButton();
    return !!(button && button.getAttribute("aria-expanded") === "true");
  }

  function nodeInsideProfile(node) {
    if (!node || !(node instanceof Element)) {
      return false;
    }
    if (
      node.closest(".st-key-topbar_profile") ||
      node.closest(".st-key-profile_menu_root") ||
      node.closest('[data-testid="stPopoverBody"]:has(.st-key-profile_menu_root)') ||
      node.closest('[data-testid="stPopoverBody"]:has(.cd-profile-help)') ||
      node.closest('[data-testid="stPopoverBody"]:has(.cd-profile-menu)') ||
      node.closest('[data-testid="stPopoverBody"]:has([class*="st-key-profile-language-"])')
    ) {
      return true;
    }
    if (!isOpen()) {
      return false;
    }
    return !!(
      node.closest('[data-baseweb="popover"]') ||
      node.closest('[data-baseweb="menu"]') ||
      node.closest('[data-baseweb="select"]') ||
      node.closest('[role="listbox"]') ||
      node.closest('[role="option"]') ||
      node.closest('[role="combobox"]') ||
      node.closest('[data-testid="stTooltipContent"]')
    );
  }

  function pointerStillInside() {
    const body = profileBody();
    const button = profileButton();
    if (body && body.matches(":hover")) {
      return true;
    }
    if (button && button.matches(":hover")) {
      return true;
    }
    if (
      doc.querySelector(
        '[data-baseweb="popover"]:hover, [data-baseweb="menu"]:hover, ' +
        '[role="listbox"]:hover, [data-testid="stTooltipContent"]:hover'
      )
    ) {
      return true;
    }
    return false;
  }

  function cancelClose() {
    if (leaveTimer) {
      win.clearTimeout(leaveTimer);
      leaveTimer = null;
    }
  }

  function closeProfile() {
    const button = profileButton();
    if (button && button.getAttribute("aria-expanded") === "true") {
      button.click();
    }
  }

  function scheduleClose() {
    cancelClose();
    leaveTimer = win.setTimeout(() => {
      leaveTimer = null;
      if (!isOpen()) {
        return;
      }
      const body = profileBody();
      if (!body) {
        // Popover DOM may be rebuilding after a widget rerun — retry once.
        leaveTimer = win.setTimeout(() => {
          leaveTimer = null;
          if (isOpen() && profileBody() && !pointerStillInside()) {
            closeProfile();
          }
        }, 180);
        return;
      }
      if (pointerStillInside()) {
        return;
      }
      closeProfile();
    }, LEAVE_MS);
  }

  function onEnter() {
    cancelClose();
  }

  function onLeave(event) {
    if (nodeInsideProfile(event.relatedTarget)) {
      cancelClose();
      return;
    }
    scheduleClose();
  }

  function unbind(node, enter, leave) {
    if (!node) {
      return;
    }
    node.removeEventListener("mouseenter", enter);
    node.removeEventListener("mouseleave", leave);
  }

  function bind() {
    const button = profileButton();
    const body = profileBody();

    if (button && button !== boundButton) {
      unbind(boundButton, onEnter, onLeave);
      boundButton = button;
      button.addEventListener("mouseenter", onEnter);
      button.addEventListener("mouseleave", onLeave);
    }

    if (body && body !== boundBody) {
      unbind(boundBody, onEnter, onLeave);
      boundBody = body;
      body.addEventListener("mouseenter", onEnter);
      body.addEventListener("mouseleave", onLeave);
      cancelClose();
    }
  }

  const body = doc.body;
  if (body instanceof win.Node) {
    observer = new win.MutationObserver(() => {
      bind();
    });
    observer.observe(body, { childList: true, subtree: true });
  }
  bind();

  win.__cdProfileLeaveCleanup = () => {
    cancelClose();
    unbind(boundButton, onEnter, onLeave);
    unbind(boundBody, onEnter, onLeave);
    boundButton = null;
    boundBody = null;
    if (observer) {
      observer.disconnect();
      observer = null;
    }
  };
})();
</script>
        """,
        height=0,
        width=0,
    )
