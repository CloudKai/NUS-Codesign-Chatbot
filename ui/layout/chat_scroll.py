"""Bounded chat-transcript scroll policy for Send / reconcile.

Streamlit has no first-class chat-anchor API. ``sync_chat_scroll`` injects a
zero-height helper that:

- treats ``.st-key-chat_panel`` as the chat scrollport (Streamlit 1.60 hosts
  the composer ``@st.fragment`` as a sibling of ``chat_log`` under the panel,
  so a nested ``chat_transcript`` wrapper is not a reliable scroller)
- snaps once on Send by assigning ``scrollTop`` (no smooth animation)
- ignores smooth ``scrollIntoView`` / ``scrollTo`` inside the chat panel
- stops following if the student scrolls away from the bottom
- does not poll, observe the whole app, or chase Thinking height changes

Overflow anchoring: the transcript keeps the browser default
(``overflow-anchor: auto`` on ``chat_log``). Thinking, error, and the sticky
composer use ``overflow-anchor: none`` so they do not fight the Send snap.
Do not globally disable overflow anchoring.

Prefer ``ui.layout.chat_scroll``.
"""

from __future__ import annotations

import streamlit.components.v1 as components

NEAR_BOTTOM_PX = 120


def sync_chat_scroll(*, mode: str = "reconcile") -> None:
    """Apply one event-driven chat scroll action.

    Args:
        mode: ``send`` snaps once and resumes follow. ``settle`` records
            near-bottom state and does not move the viewport. ``reconcile``
            snaps once only when follow is still active after a remount.
    """
    cleaned = str(mode or "reconcile").strip().lower()
    if cleaned not in {"send", "settle", "reconcile"}:
        cleaned = "reconcile"
    script = """
<script>
(() => {
  const doc = window.parent.document;
  const win = window.parent;
  const MODE = __CD_MODE__;
  const NEAR_BOTTOM_PX = __CD_NEAR_BOTTOM__;

  function scrollRoot() {
    return (
      doc.querySelector(".st-key-chat_log") ||
      doc.querySelector(".st-key-chat_panel") ||
      doc.querySelector(".st-key-chat_transcript")
    );
  }

  function state() {
    if (!win.__cdChatScroll) {
      win.__cdChatScroll = {
        follow: true,
        interceptInstalled: false,
        listenersInstalled: false,
      };
    }
    return win.__cdChatScroll;
  }

  function distanceFromBottom(root) {
    return root.scrollHeight - root.scrollTop - root.clientHeight;
  }

  function isNearBottom(root) {
    return distanceFromBottom(root) <= NEAR_BOTTOM_PX;
  }

  function snapToBottom(root) {
    if (!root) return;
    root.scrollTop = root.scrollHeight - root.clientHeight;
  }

  function inChat(node) {
    return !!(
      node &&
      node.closest &&
      node.closest(
        ".st-key-chat_panel, .st-key-chat_transcript, .st-key-chat_log, .st-key-chat_inflight, .st-key-chat_composer"
      )
    );
  }

  function installIntercept() {
    const current = state();
    if (current.interceptInstalled) return;
    current.interceptInstalled = true;
    const nativeIntoView = win.Element.prototype.scrollIntoView;
    win.Element.prototype.scrollIntoView = function (arg) {
      if (inChat(this)) {
        const behavior =
          arg && typeof arg === "object" ? arg.behavior : undefined;
        if (behavior === "smooth") return;
        return;
      }
      return nativeIntoView.apply(this, arguments);
    };
    const nativeScrollTo = win.Element.prototype.scrollTo;
    if (typeof nativeScrollTo === "function") {
      win.Element.prototype.scrollTo = function (arg0, arg1) {
        if (this === scrollRoot() || inChat(this)) {
          const behavior =
            arg0 && typeof arg0 === "object" ? arg0.behavior : undefined;
          if (behavior === "smooth") return;
        }
        return nativeScrollTo.apply(this, arguments);
      };
    }
  }

  function markUserScroll(event) {
    const root = scrollRoot();
    if (!root || !event.target || !root.contains(event.target)) return;
    win.requestAnimationFrame(() => {
      const current = scrollRoot();
      if (!current) return;
      if (!isNearBottom(current)) state().follow = false;
    });
  }

  function installListeners() {
    const current = state();
    if (current.listenersInstalled) return;
    current.listenersInstalled = true;
    doc.addEventListener("wheel", markUserScroll, { capture: true, passive: true });
    doc.addEventListener("touchmove", markUserScroll, {
      capture: true,
      passive: true,
    });
    win.addEventListener("resize", () => {
      const root = scrollRoot();
      if (root && state().follow && isNearBottom(root)) snapToBottom(root);
    });
  }

  installIntercept();
  installListeners();
  const root = scrollRoot();
  if (!root) return;
  if (MODE === "send") {
    state().follow = true;
    win.requestAnimationFrame(() => snapToBottom(scrollRoot()));
    return;
  }
  if (MODE === "settle") {
    if (root && !isNearBottom(root)) state().follow = false;
    return;
  }
  if (state().follow) {
    win.requestAnimationFrame(() => {
      const current = scrollRoot();
      if (current && state().follow) snapToBottom(current);
    });
  }
})();
</script>
"""
    script = script.replace("__CD_MODE__", repr(cleaned)).replace(
        "__CD_NEAR_BOTTOM__", str(int(NEAR_BOTTOM_PX))
    )
    components.html(script, height=0, width=0)
