"""Bounded chat-transcript scroll policy for Send / reconcile.

Streamlit has no first-class chat-anchor API. ``sync_chat_scroll`` injects a
zero-height helper that:

- treats ``.st-key-chat_feed`` as the only chat scrollport
- snaps once on Send by assigning ``scrollTop`` (no smooth animation)
- stops following if the student scrolls away from the bottom
- shows a floating scroll-down control on ``.st-key-chat_panel`` when the
  student is not near bottom
- does not poll, observe the whole app, or chase Thinking height changes

Click / scroll handlers live on ``window.parent.__cdChatScroll`` so they keep
working after Streamlit tears down the ``components.html`` iframe. Do not
attach iframe-local closures directly to the parent-document button.

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

  function api() {
    if (!win.__cdChatScroll) {
      win.__cdChatScroll = {
        follow: true,
        nearBottomPx: NEAR_BOTTOM_PX,
        listenersBound: false,
      };
    }
    const current = win.__cdChatScroll;
    current.nearBottomPx = NEAR_BOTTOM_PX;
    return current;
  }

  function scrollRoot() {
    return doc.querySelector(".st-key-chat_feed");
  }

  function distanceFromBottom(root) {
    return root.scrollHeight - root.scrollTop - root.clientHeight;
  }

  function isNearBottom(root) {
    if (!root || root.clientHeight <= 0) return false;
    return distanceFromBottom(root) <= api().nearBottomPx;
  }

  function snapToBottom(root) {
    if (!root || root.clientHeight <= 0) return;
    root.scrollTop = root.scrollHeight - root.clientHeight;
  }

  function placeScrollDownButton(button) {
    const composer = doc.querySelector(".st-key-chat_composer");
    const lift = composer ? Math.max(8, composer.offsetHeight + 8) : 56;
    button.style.bottom = lift + "px";
  }

  function updateScrollDownButton() {
    const root = scrollRoot();
    const button = scrollDownButton();
    if (!button) return;
    placeScrollDownButton(button);
    const show = !!(root && root.clientHeight > 0 && !isNearBottom(root));
    button.classList.toggle("cd-chat-scroll-down-visible", show);
  }

  function onScrollDownClick(event) {
    const target = event.target;
    if (!target || typeof target.closest !== "function") return;
    const button = target.closest("#cd-chat-scroll-down");
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    api().follow = true;
    snapToBottom(scrollRoot());
    win.requestAnimationFrame(() => {
      snapToBottom(scrollRoot());
      updateScrollDownButton();
    });
  }

  function scrollDownButton() {
    let button = doc.getElementById("cd-chat-scroll-down");
    const panel = doc.querySelector(".st-key-chat_panel");
    if (!panel) return null;
    // Host on the chat panel so the control is not clipped by composer
    // overflow or scrolled away with the feed.
    if (!button || !panel.contains(button)) {
      if (button) button.remove();
      button = doc.createElement("button");
      button.id = "cd-chat-scroll-down";
      button.type = "button";
      button.className = "cd-chat-scroll-down";
      button.setAttribute("aria-label", "Scroll to bottom");
      button.innerHTML =
        '<svg class="cd-chat-scroll-down-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
        '<path d="M12 16.5 6 10.5l1.4-1.4 4.6 4.6 4.6-4.6L18 10.5z" fill="currentColor"/>' +
        "</svg>";
      panel.appendChild(button);
    }
    placeScrollDownButton(button);
    return button;
  }

  function markUserScroll(event) {
    const root = scrollRoot();
    if (!root || !event.target || !root.contains(event.target)) return;
    win.requestAnimationFrame(() => {
      const current = scrollRoot();
      if (!current) return;
      if (!isNearBottom(current)) api().follow = false;
      updateScrollDownButton();
    });
  }

  function onFeedScroll(event) {
    const root = scrollRoot();
    if (!root || !event.target) return;
    if (event.target !== root && !root.contains(event.target)) return;
    win.requestAnimationFrame(updateScrollDownButton);
  }

  function onResize() {
    const activeRoot = scrollRoot();
    if (activeRoot && api().follow && isNearBottom(activeRoot)) {
      snapToBottom(activeRoot);
    }
    updateScrollDownButton();
  }

  // Keep handlers on the parent window and bind document listeners once.
  // components.html iframes are torn down; iframe-local closures on the
  // button then stop firing even though the node stays in the DOM.
  const current = api();
  current.scrollRoot = scrollRoot;
  current.snapToBottom = snapToBottom;
  current.updateScrollDownButton = updateScrollDownButton;
  current.onScrollDownClick = onScrollDownClick;
  current.markUserScroll = markUserScroll;
  current.onFeedScroll = onFeedScroll;
  current.onResize = onResize;
  if (!current.listenersBound) {
    doc.addEventListener(
      "click",
      (event) => {
        const live = win.__cdChatScroll;
        if (live && typeof live.onScrollDownClick === "function") {
          live.onScrollDownClick(event);
        }
      },
      true
    );
    doc.addEventListener(
      "wheel",
      (event) => {
        const live = win.__cdChatScroll;
        if (live && typeof live.markUserScroll === "function") {
          live.markUserScroll(event);
        }
      },
      { capture: true, passive: true }
    );
    doc.addEventListener(
      "touchmove",
      (event) => {
        const live = win.__cdChatScroll;
        if (live && typeof live.markUserScroll === "function") {
          live.markUserScroll(event);
        }
      },
      { capture: true, passive: true }
    );
    doc.addEventListener(
      "scroll",
      (event) => {
        const live = win.__cdChatScroll;
        if (live && typeof live.onFeedScroll === "function") {
          live.onFeedScroll(event);
        }
      },
      { capture: true, passive: true }
    );
    win.addEventListener("resize", () => {
      const live = win.__cdChatScroll;
      if (live && typeof live.onResize === "function") {
        live.onResize();
      }
    });
    current.listenersBound = true;
  }

  scrollDownButton();
  const root = scrollRoot();
  if (!root) {
    updateScrollDownButton();
    return;
  }
  if (MODE === "send") {
    api().follow = true;
    win.requestAnimationFrame(() => {
      snapToBottom(scrollRoot());
      updateScrollDownButton();
    });
    return;
  }
  if (MODE === "settle") {
    if (!isNearBottom(root)) api().follow = false;
    updateScrollDownButton();
    return;
  }
  if (api().follow) {
    win.requestAnimationFrame(() => {
      const liveRoot = scrollRoot();
      if (liveRoot && api().follow) snapToBottom(liveRoot);
      updateScrollDownButton();
    });
    return;
  }
  updateScrollDownButton();
})();
</script>
"""
    script = script.replace("__CD_MODE__", repr(cleaned)).replace(
        "__CD_NEAR_BOTTOM__", str(int(NEAR_BOTTOM_PX))
    )
    components.html(script, height=0, width=0)
