"""Bounded chat-transcript scroll policy for Send / reconcile.

Streamlit has no first-class chat-anchor API. ``sync_chat_scroll`` injects a
zero-height helper that:

- treats ``.st-key-chat_feed`` as the only chat scrollport
- snaps to the bottom on Send (pending user bubble + thinking)
- remembers ``awaitingReplyReveal`` across the reply remount so a feed that
  resets to the top cannot clear follow before the coach bubble is pinned
- on reply remount, arms ``awaitingReplyReveal`` and pins the **top** of the
  latest coach message to the top of the feed (clamped for short replies)
- on reconcile, pins only when follow or a pending reply-reveal is still armed
- stops the pending reveal when the student scrolls/swipes away from the bottom
- hosts the scroll-down control on ``document.body`` (fixed) and keeps a
  parent-owned rAF ensure loop (``ensureGeneration``) so Review / New chat
  remounts that paint Chat after the iframe is torn down still recover the
  control once the feed has real geometry
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
# Extra frames after Send / reply remount so Streamlit can finish painting
# the new bubble height before scrollTop is applied.
FOLLOW_SNAP_FRAMES = 8
# Review / New chat remounts often finish painting Chat well after the
# components.html iframe is gone. Keep a parent-owned rAF ensure for this
# many frames (~1.5s) or until feed geometry is stable.
SCROLL_DOWN_ENSURE_FRAMES = 90


def sync_chat_scroll(*, mode: str = "reconcile") -> None:
    """Apply one event-driven chat scroll action.

    Args:
        mode: ``send`` snaps to the bottom, arms reply reveal, and resumes
            follow. ``settle`` records near-bottom state and does not move the
            viewport. ``reply`` arms reveal and pins the latest coach reply top
            after a remount (stage move or completed coach turn). ``reconcile``
            pins only when follow or a pending reply-reveal is still armed.
    """
    cleaned = str(mode or "reconcile").strip().lower()
    if cleaned not in {"send", "settle", "reconcile", "reply"}:
        cleaned = "reconcile"
    script = """
<script>
(() => {
  const doc = window.parent.document;
  const win = window.parent;
  const MODE = __CD_MODE__;
  const NEAR_BOTTOM_PX = __CD_NEAR_BOTTOM__;
  const FOLLOW_SNAP_FRAMES = __CD_FOLLOW_FRAMES__;
  const SCROLL_DOWN_ENSURE_FRAMES = __CD_ENSURE_FRAMES__;

  function api() {
    if (!win.__cdChatScroll) {
      win.__cdChatScroll = {
        follow: true,
        awaitingReplyReveal: false,
        snapping: false,
        nearBottomPx: NEAR_BOTTOM_PX,
        listenersBound: false,
        ensureGeneration: 0,
        ensureStableFrames: 0,
        ensureLastScrollHeight: -1,
      };
    }
    const current = win.__cdChatScroll;
    current.nearBottomPx = NEAR_BOTTOM_PX;
    if (typeof current.awaitingReplyReveal !== "boolean") {
      current.awaitingReplyReveal = false;
    }
    if (typeof current.ensureGeneration !== "number") {
      current.ensureGeneration = 0;
    }
    if (typeof current.ensureStableFrames !== "number") {
      current.ensureStableFrames = 0;
    }
    if (typeof current.ensureLastScrollHeight !== "number") {
      current.ensureLastScrollHeight = -1;
    }
    return current;
  }

  function schedule(fn) {
    win.requestAnimationFrame(fn);
  }

  function scrollRoot() {
    return doc.querySelector(".st-key-chat_feed");
  }

  function chatPanel() {
    return doc.querySelector(".st-key-chat_panel");
  }

  function distanceFromBottom(root) {
    return root.scrollHeight - root.scrollTop - root.clientHeight;
  }

  function isNearBottom(root) {
    // Unsized feeds are not "near bottom"; keep ensuring until layout lands.
    if (!root || root.clientHeight <= 0) return false;
    return distanceFromBottom(root) <= api().nearBottomPx;
  }

  function snapToBottom(root) {
    if (!root || root.clientHeight <= 0) return;
    root.scrollTop = root.scrollHeight - root.clientHeight;
  }

  function latestCoachReply() {
    const nodes = doc.querySelectorAll(
      '.st-key-chat_log [data-testid="stChatMessage"]:has([aria-label="Chat message from assistant"])'
    );
    return nodes.length ? nodes[nodes.length - 1] : null;
  }

  function revealLatestCoachReply(root) {
    if (!root || root.clientHeight <= 0) return;
    const reply = latestCoachReply();
    if (!reply) {
      snapToBottom(root);
      return;
    }
    // Pin the coach message top to the feed top; clamp when the reply is
    // shorter than the viewport (not enough content below to scroll further).
    const rootRect = root.getBoundingClientRect();
    const replyRect = reply.getBoundingClientRect();
    const delta = replyRect.top - rootRect.top;
    const maxScroll = Math.max(0, root.scrollHeight - root.clientHeight);
    const next = root.scrollTop + delta;
    root.scrollTop = Math.max(0, Math.min(next, maxScroll));
  }

  function shouldRevealReply() {
    const current = api();
    return !!(current.awaitingReplyReveal || current.follow);
  }

  function isChatSurfaceVisible(panel) {
    if (!panel) return false;
    const column = panel.closest('[data-testid="stColumn"]') || panel;
    const style = win.getComputedStyle(column);
    if (style.display === "none" || style.visibility === "hidden") return false;
    const rect = column.getBoundingClientRect();
    return rect.width > 8 && rect.height > 8;
  }

  function placeScrollDownButton(button) {
    const panel = chatPanel();
    if (!panel) return;
    const panelRect = panel.getBoundingClientRect();
    // Mid-remount panels can report empty boxes; keep the last good spot.
    if (panelRect.width < 8 || panelRect.height < 8) return;
    const composer = doc.querySelector(".st-key-chat_composer");
    const composerRect = composer ? composer.getBoundingClientRect() : null;
    let bottom = Math.max(8, win.innerHeight - panelRect.bottom + 56);
    if (
      composerRect &&
      composerRect.height > 8 &&
      composerRect.top > 8 &&
      composerRect.top < win.innerHeight
    ) {
      bottom = Math.max(8, win.innerHeight - composerRect.top + 8);
    }
    // Composer at y≈0 during remount used to push bottom past the viewport.
    bottom = Math.min(bottom, Math.max(8, win.innerHeight - 40));
    button.style.left = panelRect.left + panelRect.width / 2 + "px";
    button.style.bottom = bottom + "px";
  }

  function updateScrollDownButton() {
    const root = scrollRoot();
    const panel = chatPanel();
    const button = scrollDownButton();
    if (!button) return;
    const surfaceVisible = isChatSurfaceVisible(panel);
    if (surfaceVisible) placeScrollDownButton(button);
    const show = !!(
      surfaceVisible &&
      root &&
      root.clientHeight > 8 &&
      !isNearBottom(root)
    );
    button.classList.toggle("cd-chat-scroll-down-visible", show);
  }

  function syncFollowFromViewport() {
    // Ignore scroll events caused by our own stick while the coach reply is
    // still painting; otherwise follow clears mid-snap. Do not clear
    // awaitingReplyReveal here: reply remounts often reset scrollTop to 0
    // before this script runs, which would cancel the pending reveal.
    if (api().snapping) return;
    const root = scrollRoot();
    if (!root || root.clientHeight <= 0) return;
    api().follow = isNearBottom(root);
  }

  function onScrollDownClick(event) {
    const target = event.target;
    if (!target || typeof target.closest !== "function") return;
    const button = target.closest("#cd-chat-scroll-down");
    if (!button) return;
    event.preventDefault();
    event.stopPropagation();
    api().follow = true;
    api().awaitingReplyReveal = true;
    keepRevealingCoachReply(FOLLOW_SNAP_FRAMES);
  }

  function scrollDownButton() {
    let button = doc.getElementById("cd-chat-scroll-down");
    // Host on document.body with position:fixed. Appending under
    // .st-key-chat_panel loses the node whenever Streamlit remounts that
    // block after Send or Journey/Sources tab switches.
    if (!button || button.parentElement !== doc.body) {
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
      doc.body.appendChild(button);
    }
    placeScrollDownButton(button);
    return button;
  }

  function markUserScroll(event) {
    const root = scrollRoot();
    if (!root || !event.target || !root.contains(event.target)) return;
    // Wheel / touch: the student took over; cancel any in-flight stick and
    // the pending post-reply reveal.
    schedule(() => {
      api().snapping = false;
      syncFollowFromViewport();
      if (!api().follow) api().awaitingReplyReveal = false;
      updateScrollDownButton();
    });
  }

  function onFeedScroll(event) {
    const root = scrollRoot();
    if (!root || !event.target) return;
    if (event.target !== root && !root.contains(event.target)) return;
    schedule(() => {
      syncFollowFromViewport();
      updateScrollDownButton();
    });
  }

  function onResize() {
    const activeRoot = scrollRoot();
    if (activeRoot && shouldRevealReply()) {
      revealLatestCoachReply(activeRoot);
    }
    updateScrollDownButton();
  }

  function finishSnapFrames(framesLeft, apply, revealPass) {
    const allow = revealPass ? shouldRevealReply() : api().follow;
    if (!allow) {
      api().snapping = false;
      updateScrollDownButton();
      return;
    }
    api().snapping = true;
    if (revealPass) api().follow = true;
    const root = scrollRoot();
    if (root && root.clientHeight > 0) apply(root);
    updateScrollDownButton();
    if (framesLeft > 1) {
      schedule(() => finishSnapFrames(framesLeft - 1, apply, revealPass));
      return;
    }
    schedule(() => {
      api().snapping = false;
      if (revealPass) api().awaitingReplyReveal = false;
      const liveRoot = scrollRoot();
      if (liveRoot && isNearBottom(liveRoot)) api().follow = true;
      updateScrollDownButton();
    });
  }

  function keepSnappingToBottom(framesLeft) {
    finishSnapFrames(framesLeft, snapToBottom, false);
  }

  function keepRevealingCoachReply(framesLeft) {
    finishSnapFrames(framesLeft, revealLatestCoachReply, true);
  }

  // Keep handlers on the parent window and bind document listeners once.
  // components.html iframes are torn down; iframe-local closures on the
  // button then stop firing even though the node stays in the DOM.
  const current = api();
  current.scrollRoot = scrollRoot;
  current.snapToBottom = snapToBottom;
  current.revealLatestCoachReply = revealLatestCoachReply;
  current.updateScrollDownButton = updateScrollDownButton;
  current.onScrollDownClick = onScrollDownClick;
  current.markUserScroll = markUserScroll;
  current.onFeedScroll = onFeedScroll;
  current.onResize = onResize;
  current.keepSnappingToBottom = keepSnappingToBottom;
  current.keepRevealingCoachReply = keepRevealingCoachReply;
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

  function feedGeometryReady(root) {
    if (!root || root.clientHeight <= 8) return false;
    const height = root.scrollHeight;
    const state = api();
    if (height === state.ensureLastScrollHeight) {
      state.ensureStableFrames += 1;
    } else {
      state.ensureLastScrollHeight = height;
      state.ensureStableFrames = 0;
    }
    // Two consecutive frames with the same scrollHeight means layout settled.
    return state.ensureStableFrames >= 2;
  }

  function ensureScrollDown(generation, framesLeft) {
    // Parent-owned: scheduled via win.__cdChatScroll so iframe teardown cannot
    // drop the chain after Review / New chat remounts Chat.
    const state = win.__cdChatScroll;
    if (!state || state.ensureGeneration !== generation) return;
    if (typeof state.updateScrollDownButton === "function") {
      state.updateScrollDownButton();
    }
    const root =
      typeof state.scrollRoot === "function" ? state.scrollRoot() : null;
    const ready = feedGeometryReady(root);
    if (ready || framesLeft <= 1) {
      if (typeof state.updateScrollDownButton === "function") {
        state.updateScrollDownButton();
      }
      return;
    }
    schedule(() => ensureScrollDown(generation, framesLeft - 1));
  }

  function startEnsureScrollDown() {
    const state = api();
    state.ensureGeneration += 1;
    state.ensureStableFrames = 0;
    state.ensureLastScrollHeight = -1;
    state.ensureScrollDown = ensureScrollDown;
    const generation = state.ensureGeneration;
    scrollDownButton();
    updateScrollDownButton();
    schedule(() => ensureScrollDown(generation, SCROLL_DOWN_ENSURE_FRAMES));
  }

  scrollDownButton();
  const root = scrollRoot();
  if (!root) {
    startEnsureScrollDown();
    return;
  }
  if (MODE === "send") {
    api().follow = true;
    api().awaitingReplyReveal = true;
    // Pending user + thinking are not yet a coach bubble in chat_log.
    keepSnappingToBottom(FOLLOW_SNAP_FRAMES);
    startEnsureScrollDown();
    return;
  }
  if (MODE === "settle") {
    syncFollowFromViewport();
    startEnsureScrollDown();
    return;
  }
  if (MODE === "reply") {
    // Stage-move remounts never go through Send, so follow may already be
    // false from a scrollTop=0 reset. Arm reveal the same way Send does.
    api().follow = true;
    api().awaitingReplyReveal = true;
    keepRevealingCoachReply(FOLLOW_SNAP_FRAMES);
    startEnsureScrollDown();
    return;
  }
  // reconcile: pin latest coach top only when follow / pending reveal is
  // still armed. Do not steal the viewport after the student scrolled away.
  if (shouldRevealReply()) {
    keepRevealingCoachReply(FOLLOW_SNAP_FRAMES);
  }
  startEnsureScrollDown();
})();
</script>
"""
    script = (
        script.replace("__CD_MODE__", repr(cleaned))
        .replace("__CD_NEAR_BOTTOM__", str(int(NEAR_BOTTOM_PX)))
        .replace("__CD_FOLLOW_FRAMES__", str(int(FOLLOW_SNAP_FRAMES)))
        .replace("__CD_ENSURE_FRAMES__", str(int(SCROLL_DOWN_ENSURE_FRAMES)))
    )
    components.html(script, height=0, width=0)
