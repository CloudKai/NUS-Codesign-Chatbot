"""Profile settings popover for local appearance, coaching style, and logout."""

from __future__ import annotations

import json
from html import escape

import streamlit as st
import streamlit.components.v1 as components

from backend.student_journey import RESPONSE_DETAILS, normalize_journey

from ui.auth_gate import logout_user
from ui.components import profile_initial
from ui.constants import APPEARANCE_MODES
from ui.html_embed import wrap_component_html
from ui.menu_popovers import close_menu_popover, menu_popover_widget_key
from ui.runtime import store
from ui.session import save_journey
from ui.settings import persist_appearance


COACHING_STYLE_LABELS = {
    "short": "Guide",
    "long": "Free",
}
COACHING_STYLE_VALUES = {
    label: detail for detail, label in COACHING_STYLE_LABELS.items()
}
COACHING_STYLE_COPY = {
    "short": (
        "Lighter coaching through the Thinking Path; progress once your "
        "thinking is workable."
    ),
    "long": (
        "Bring what you already have to this stage, get a check, then Next. "
        "The coach will not hold you to improve structure."
    ),
}


def persist_display_name() -> None:
    """Store the local display name used by the profile shell."""
    cleaned = " ".join(str(st.session_state.profile_display_name or "").split())[:80]
    st.session_state.display_name = cleaned or "Student"
    store.update_thread(
        st.session_state.thread_id,
        metadata={"display_name": st.session_state.display_name},
    )


def _sync_profile_trigger_label(display_name: str) -> None:
    """Update the static sidebar identity after a fragment-local name edit."""
    encoded_name = json.dumps(display_name)
    encoded_initials = json.dumps(profile_initial(display_name))
    components.html(
        wrap_component_html(
            f"""
<script>
(() => {{
  const root = window.parent.document.querySelector('.st-key-sidebar_profile');
  if (!root) {{
    return;
  }}
  const name = root.querySelector('.cd-sidebar-profile-name');
  const avatar = root.querySelector('.cd-sidebar-profile-avatar');
  if (name) {{
    name.textContent = {encoded_name};
  }}
  if (avatar) {{
    avatar.textContent = {encoded_initials};
  }}
}})();
</script>
            """
        ),
        height=0,
        width=0,
    )


@st.fragment
def _render_display_name_fragment(display_name: str, *, collapsed: bool) -> None:
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
    if not collapsed:
        _sync_profile_trigger_label(current_name)


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


def _coaching_style_caption(detail: str) -> str:
    """Return the short explanation shown under one coaching-style option."""
    return COACHING_STYLE_COPY[detail]


@st.fragment
def _render_coaching_style_fragment() -> None:
    """Render response-detail preferences without redrawing the workspace."""
    st.session_state["_topbar_guidance_fragment_runs"] = (
        int(st.session_state.get("_topbar_guidance_fragment_runs") or 0) + 1
    )
    journey = normalize_journey(st.session_state.learning_journey)
    current_detail = journey["response_detail"]
    labels = [COACHING_STYLE_LABELS[detail] for detail in RESPONSE_DETAILS]
    captions = [_coaching_style_caption(detail) for detail in RESPONSE_DETAILS]
    st.session_state.setting_coaching_style = COACHING_STYLE_LABELS[current_detail]
    with st.container(key="profile_coaching_style"):
        st.radio(
            "Coaching style",
            labels,
            captions=captions,
            key="setting_coaching_style",
            on_change=_persist_coaching_style,
            width="stretch",
        )


def _render_profile_menu_body(*, display_name: str, collapsed: bool) -> None:
    """Render the settings popover contents shared by expanded and collapsed rails."""
    with st.container(key="profile_menu_root"):
        st.markdown(
            '<div class="cd-profile-menu" hidden></div>',
            unsafe_allow_html=True,
        )
        _render_display_name_fragment(display_name, collapsed=collapsed)
        st.segmented_control(
            "Appearance",
            APPEARANCE_MODES,
            key="setting_appearance",
            # This widget intentionally stays outside a fragment. Its
            # normal widget rerun must re-execute streamlit_app.py so
            # the complete theme and layout stylesheet is re-injected.
            on_change=persist_appearance,
        )
        _render_coaching_style_fragment()
        st.divider()
        with st.container(key="profile-logout"):
            st.button(
                "Logout",
                key="profile-logout-button",
                use_container_width=True,
                type="secondary",
                on_click=_on_open_logout_confirm,
            )


def _on_open_logout_confirm() -> None:
    """Arm logout confirmation and close Settings so only the dialog remains."""
    st.session_state.pending_logout_confirm = True
    close_menu_popover("profile-settings")


def dismiss_logout_dialog() -> None:
    """Clear pending logout when the dialog is closed via X / outside / Esc."""
    st.session_state.pop("pending_logout_confirm", None)


@st.dialog("Log out?", on_dismiss=dismiss_logout_dialog)
def confirm_logout_dialog() -> None:
    """Confirm sign-out from the profile settings menu."""
    if not st.session_state.get("pending_logout_confirm"):
        return
    st.write(
        "You will be signed out of this session on this device. "
        "You can sign in again anytime."
    )
    cancel_column, confirm_column = st.columns(2)
    if cancel_column.button(
        "Cancel",
        use_container_width=True,
        key="profile-logout-cancel",
    ):
        dismiss_logout_dialog()
        st.rerun()
    if confirm_column.button(
        "Logout",
        type="primary",
        use_container_width=True,
        key="profile-logout-confirm",
    ):
        dismiss_logout_dialog()
        logout_user()


def mount_pending_logout_dialog() -> None:
    """Open the logout confirmation when Settings requested it."""
    if not st.session_state.get("pending_logout_confirm"):
        return
    confirm_logout_dialog()


def render_profile_menu(*, collapsed: bool = False) -> None:
    """Render the sidebar identity row; only the settings icon opens the menu."""
    display_name = str(st.session_state.get("display_name") or "Student")
    initials = profile_initial(display_name)
    settings_popover_key = menu_popover_widget_key("profile-settings")
    with st.container(key="sidebar_profile"):
        if collapsed:
            with st.popover(
                ":material/settings:",
                type="tertiary",
                help="Settings",
                key=settings_popover_key,
            ):
                _render_profile_menu_body(
                    display_name=display_name,
                    collapsed=True,
                )
            return

        identity_col, settings_col = st.columns([0.82, 0.18], gap="small")
        with identity_col:
            # Static identity — avatar and name are not interactive.
            st.markdown(
                '<div class="cd-sidebar-profile-identity" aria-hidden="false">'
                f'<span class="cd-sidebar-profile-avatar" aria-hidden="true">'
                f"{escape(initials)}</span>"
                f'<span class="cd-sidebar-profile-name">{escape(display_name)}</span>'
                "</div>",
                unsafe_allow_html=True,
            )
        with settings_col:
            with st.container(key="sidebar_profile_settings"):
                with st.popover(
                    ":material/settings:",
                    type="tertiary",
                    help="Settings",
                    key=settings_popover_key,
                ):
                    _render_profile_menu_body(
                        display_name=display_name,
                        collapsed=False,
                    )


def inject_profile_leave_helper() -> None:
    """Install the leave-to-close script outside the avatar layout chain."""
    with st.container(key="profile_leave_helper"):
        _sync_profile_popover_close_on_leave()


def _sync_profile_popover_close_on_leave() -> None:
    """Close the profile menu only after the pointer leaves its chrome.

    Desktop (fine pointer + hover): mouseleave closes after a short delay.
    Touch / coarse pointers: leave-to-close is disabled — the first tap inside
    the menu otherwise looks like a leave (no :hover) and closes immediately.
    Streamlit already closes on outside tap / Escape.
    """
    components.html(
        wrap_component_html(
            """
<script>
(() => {
  const doc = window.parent.document;
  const win = window.parent;
  const isNode = (value) => Boolean(value) && typeof value.nodeType === "number";
  const LEAVE_MS = 420;
  const INTERACT_MS = 1800;
  const finePointer = win.matchMedia(
    "(hover: hover) and (pointer: fine)"
  ).matches;

  if (typeof win.__cdProfileLeaveCleanup === "function") {
    try { win.__cdProfileLeaveCleanup(); } catch (_) {}
  }

  // Touch / stylus: do not auto-close on leave — first in-menu tap would
  // schedule a close because :hover never sticks on those devices.
  if (!finePointer) {
    win.__cdProfileLeaveCleanup = () => {};
    return;
  }

  let leaveTimer = null;
  let boundBody = null;
  let boundButton = null;
  let observer = null;

  function profileButton() {
    return doc.querySelector(
      '.st-key-sidebar_profile [data-testid="stPopover"] button'
    );
  }

  function profileBody() {
    return doc.querySelector(
      '[data-testid="stPopoverBody"]:has(.st-key-profile_menu_root), ' +
      '[data-testid="stPopoverBody"]:has(.cd-profile-menu), ' +
      '[data-testid="stPopoverBody"][aria-label=":material/settings:"], ' +
      '[data-testid="stPopoverBody"][aria-label="Settings"]'
    );
  }

  function isOpen() {
    const button = profileButton();
    return !!(button && button.getAttribute("aria-expanded") === "true");
  }

  function markInteract() {
    win.__cdProfileInteractUntil = Date.now() + INTERACT_MS;
    cancelClose();
  }

  function recentlyInteracted() {
    return !!(
      win.__cdProfileInteractUntil &&
      Date.now() < win.__cdProfileInteractUntil
    );
  }

  function nodeInsideProfile(node) {
    if (!node || !(node instanceof Element)) {
      return false;
    }
    if (
      node.closest(".st-key-sidebar_profile") ||
      node.closest(".st-key-profile_menu_root") ||
      node.closest('[data-testid="stPopoverBody"]:has(.st-key-profile_menu_root)') ||
      node.closest('[data-testid="stPopoverBody"]:has(.cd-profile-menu)') ||
      node.closest('[data-testid="stPopoverBody"][aria-label=":material/settings:"]') ||
      node.closest('[data-testid="stPopoverBody"][aria-label="Settings"]')
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
    if (nodeInsideProfile(doc.activeElement)) {
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

  function shouldStayOpen() {
    if (!isOpen()) {
      return false;
    }
    if (recentlyInteracted()) {
      return true;
    }
    if (pointerStillInside()) {
      return true;
    }
    // Popover DOM can briefly detach during a widget/fragment rerun.
    if (!profileBody() && isOpen()) {
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
    if (shouldStayOpen()) {
      return;
    }
    const button = profileButton();
    if (button && button.getAttribute("aria-expanded") === "true") {
      button.click();
    }
  }

  function scheduleClose() {
    cancelClose();
    leaveTimer = win.setTimeout(() => {
      leaveTimer = null;
      if (!isOpen() || shouldStayOpen()) {
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

  function onPointerDown(event) {
    if (nodeInsideProfile(event.target)) {
      markInteract();
    }
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
      markInteract();
    }
  }

  const body = doc.body;
  if (isNode(body)) {
    body.addEventListener("pointerdown", onPointerDown, true);
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
    if (body instanceof win.Node) {
      body.removeEventListener("pointerdown", onPointerDown, true);
    }
    if (observer) {
      observer.disconnect();
      observer = null;
    }
  };
})();
</script>
            """
        ),
        height=0,
        width=0,
    )
