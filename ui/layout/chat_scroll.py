"""Bounded chat-transcript scroll policy for notebook paging and Send.

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

from time import monotonic_ns

import streamlit.components.v1 as components

from ui.html_embed import wrap_component_html

NEAR_BOTTOM_PX = 120
# Keep the floating control independent from the wider follow threshold. A
# student who is close to (but not at) the end should still have an explicit
# way to jump to the latest message.
SCROLL_CONTROL_THRESHOLD_PX = 16
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
        mode: ``open`` snaps a newly opened notebook to the exact bottom;
        ``prepend`` restores the reading position after older rows are added;
        ``send`` snaps to the bottom, arms reply reveal, and resumes
            follow. ``settle`` records near-bottom state and does not move the
            viewport. ``reply`` arms reveal and pins the latest coach reply top
            after a remount (stage move or completed coach turn). ``reconcile``
            pins only when follow or a pending reply-reveal is still armed.
    """
    cleaned = str(mode or "reconcile").strip().lower()
    if cleaned not in {"open", "prepend", "send", "settle", "reconcile", "reply"}:
        cleaned = "reconcile"
    # ``components.html`` may keep an identical srcdoc iframe across a
    # fragment remount. A monotonic token makes each helper invocation
    # rehydrate the parent controller without any DOM observer or global
    # mutable counter.
    sync_token = monotonic_ns()
    script = """
<script>
(() => {
  const doc = window.parent.document;
  const win = window.parent;
  const SYNC_TOKEN = __CD_SYNC_TOKEN__;
  const MODE = __CD_MODE__;
  const NEAR_BOTTOM_PX = __CD_NEAR_BOTTOM__;
  const SCROLL_CONTROL_THRESHOLD_PX = __CD_SCROLL_CONTROL_THRESHOLD__;
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
        boundScrollRoot: null,
        boundScrollHandler: null,
        documentHandlers: null,
        scheduledFrame: 0,
        scheduledCallbacks: [],
        pagingLocked: false,
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
    if (!("boundScrollRoot" in current)) {
      current.boundScrollRoot = null;
    }
    if (!("boundScrollHandler" in current)) {
      current.boundScrollHandler = null;
    }
    if (!("documentHandlers" in current)) {
      current.documentHandlers = null;
    }
    if (typeof current.scheduledFrame !== "number") {
      current.scheduledFrame = 0;
    }
    if (!Array.isArray(current.scheduledCallbacks)) {
      current.scheduledCallbacks = [];
    }
    if (typeof current.pagingLocked !== "boolean") {
      current.pagingLocked = false;
    }
    return current;
  }

  function schedule(fn) {
    const state = api();
    state.scheduledCallbacks.push(fn);
    if (state.scheduledFrame) return;
    state.scheduledFrame = win.requestAnimationFrame(() => {
      state.scheduledFrame = 0;
      const callbacks = state.scheduledCallbacks.splice(0);
      callbacks.forEach((callback) => callback());
    });
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

  function bindScrollRoot(root, force = false) {
    const state = api();
    if (!force && state.boundScrollRoot === root && state.boundScrollHandler) {
      return;
    }
    if (state.boundScrollRoot && state.boundScrollHandler) {
      state.boundScrollRoot.removeEventListener("scroll", state.boundScrollHandler);
    }
    state.boundScrollRoot = root || null;
    state.boundScrollHandler = null;
    if (!root) return;

    // Element scroll events do not reliably reach a document-level capture
    // listener after Streamlit replaces the feed. Bind the current scrollport
    // directly and refresh the fixed control on every manual scroll.
    const handler = () => {
      schedule(() => {
        syncFollowFromViewport();
        updateScrollDownButton();
      });
    };
    state.boundScrollHandler = handler;
    root.addEventListener("scroll", handler, { passive: true });
  }

  function removeDocumentListeners() {
    const state = api();
    const handlers = state.documentHandlers;
    if (!handlers) return;
    doc.removeEventListener("click", handlers.click, true);
    doc.removeEventListener("wheel", handlers.wheel, true);
    doc.removeEventListener("touchmove", handlers.touchmove, true);
    doc.removeEventListener("scroll", handlers.scroll, true);
    win.removeEventListener("resize", handlers.resize);
    state.documentHandlers = null;
  }

  function bindDocumentListeners() {
    const state = api();
    // Streamlit can leave the body-hosted button behind while tearing down
    // the component iframe that installed these callbacks. Rehydrate the
    // parent listeners on every sync instead of trusting a stale boolean.
    removeDocumentListeners();
    const handlers = {
      click: (event) => {
        const live = win.__cdChatScroll;
        if (live && typeof live.onScrollDownClick === "function") {
          live.onScrollDownClick(event);
        }
      },
      wheel: (event) => {
        const live = win.__cdChatScroll;
        if (live && typeof live.markUserScroll === "function") {
          live.markUserScroll(event);
        }
      },
      touchmove: (event) => {
        const live = win.__cdChatScroll;
        if (live && typeof live.markUserScroll === "function") {
          live.markUserScroll(event);
        }
      },
      scroll: (event) => {
        const live = win.__cdChatScroll;
        if (live && typeof live.onFeedScroll === "function") {
          live.onFeedScroll(event);
        }
      },
      resize: () => {
        const live = win.__cdChatScroll;
        if (live && typeof live.onResize === "function") {
          live.onResize();
        }
      },
    };
    doc.addEventListener("click", handlers.click, true);
    doc.addEventListener("wheel", handlers.wheel, {
      capture: true,
      passive: true,
    });
    doc.addEventListener("touchmove", handlers.touchmove, {
      capture: true,
      passive: true,
    });
    doc.addEventListener("scroll", handlers.scroll, {
      capture: true,
      passive: true,
    });
    win.addEventListener("resize", handlers.resize);
    state.documentHandlers = handlers;
    state.listenersBound = true;
  }

  function updateScrollDownButton() {
    const root = scrollRoot();
    const panel = chatPanel();
    bindScrollRoot(root);
    const button = scrollDownButton();
    if (!button) return;
    const surfaceVisible = isChatSurfaceVisible(panel);
    if (surfaceVisible) placeScrollDownButton(button);
    const show = !!(
      surfaceVisible &&
      root &&
      root.clientHeight > 8 &&
      distanceFromBottom(root) > SCROLL_CONTROL_THRESHOLD_PX
    );
    button.classList.toggle("cd-chat-scroll-down-visible", show);
    button.dataset.cdChatScrollState = show ? "away" : "bottom";
    button.setAttribute("aria-hidden", show ? "false" : "true");
    button.tabIndex = show ? 0 : -1;
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
    api().awaitingReplyReveal = false;
    keepSnappingToBottom(FOLLOW_SNAP_FRAMES);
  }

  function scrollDownButton() {
    const buttons = Array.from(doc.querySelectorAll("#cd-chat-scroll-down"));
    let button =
      buttons.find((candidate) => candidate.parentElement === doc.body) ||
      buttons[0] ||
      null;
    buttons.forEach((candidate) => {
      if (candidate !== button) candidate.remove();
    });
    // Host on document.body with position:fixed. Appending under
    // .st-key-chat_panel loses the node whenever Streamlit remounts that
    // block after Send or Journey/Sources tab switches.
    if (!button) {
      button = doc.createElement("button");
      button.id = "cd-chat-scroll-down";
      button.type = "button";
      button.className = "cd-chat-scroll-down";
      button.innerHTML =
        '<svg class="cd-chat-scroll-down-icon" viewBox="0 0 24 24" aria-hidden="true" focusable="false">' +
        '<path d="M12 16.5 6 10.5l1.4-1.4 4.6 4.6 4.6-4.6L18 10.5z" fill="currentColor"/>' +
        "</svg>";
    }
    if (button.parentElement !== doc.body) doc.body.appendChild(button);
    button.className = "cd-chat-scroll-down";
    button.type = "button";
    button.setAttribute("aria-label", "Scroll to bottom");
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

  function restorePrependedViewport(framesLeft) {
    const state = api();
    const root = scrollRoot();
    const anchor = win.__cdChatScrollPrependAnchor;
    if (!root || !anchor || root.clientHeight <= 0) return;
    const oldTop = Number(anchor.top || 0);
    const oldHeight = Number(anchor.height || 0);
    const anchorId = String(anchor.messageId || "");
    // Without a stable marker, retain the captured reading position and use
    // the measured height delta. The marker branch below can additionally
    // account for a remount that preserved or reset the live scrollTop.
    let nextTop = oldTop + Math.max(0, root.scrollHeight - oldHeight);
    if (anchorId) {
      const marker = Array.from(
        root.querySelectorAll("[data-cd-message-id]")
      ).find(
        (candidate) =>
          String(candidate.getAttribute("data-cd-message-id") || "") === anchorId
      );
      if (marker) {
        // Prefer the stable message marker over a raw height delta. Streamlit
        // can change markdown/attachment height across several paints; using
        // the marker's current offset keeps the same message at the same
        // viewport position even when the inserted page reflows.
        const rootRect = root.getBoundingClientRect();
        const markerRect = marker.getBoundingClientRect();
        const oldOffset = Number(anchor.offset || 0);
        const currentOffset = markerRect.top - rootRect.top;
        // Use the live scrollTop because Streamlit may preserve the current
        // value or reset it while the feed remounts. In either case, applying
        // the marker's offset delta keeps the same message at the same
        // viewport position. Adding the captured top here would double-count
        // it when the browser preserved a non-zero scrollTop.
        nextTop = root.scrollTop + currentOffset - oldOffset;
      }
    }
    const maxScroll = Math.max(0, root.scrollHeight - root.clientHeight);
    root.scrollTop = Math.max(0, Math.min(nextTop, maxScroll));
    if (framesLeft <= 1) {
      delete win.__cdChatScrollPrependAnchor;
      state.follow = isNearBottom(root);
      updateScrollDownButton();
      return;
    }
    schedule(() => restorePrependedViewport(framesLeft - 1));
  }

  // Keep handlers on the parent window and rehydrate parent listeners every
  // time this helper runs. components.html iframes are torn down; iframe-local
  // closures on the button then stop firing even though the node stays in DOM.
  const current = api();
  current.lastSyncToken = SYNC_TOKEN;
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
  bindDocumentListeners();
  // Force a detach/attach for the current feed on each helper run. The
  // ensure loop also detects a replaced Streamlit feed between remounts.
  bindScrollRoot(scrollRoot(), true);

  function feedGeometryReady(root) {
    if (!root || root.clientHeight <= 8) return false;
    const height = root.scrollHeight;
    const state = api();
    // Streamlit can paint an empty feed first and append the persisted
    // transcript after this helper has run. Keep the parent-owned ensure loop
    // alive until there is either meaningful overflow or the bounded budget
    // expires; otherwise a long notebook remount would leave the control in
    // its stale hidden state.
    if (height <= root.clientHeight + SCROLL_CONTROL_THRESHOLD_PX) {
      state.ensureLastScrollHeight = height;
      state.ensureStableFrames = 0;
      return false;
    }
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
    api().pagingLocked = true;
    api().follow = true;
    api().awaitingReplyReveal = true;
    // Pending user + thinking are not yet a coach bubble in chat_log.
    keepSnappingToBottom(FOLLOW_SNAP_FRAMES);
    startEnsureScrollDown();
    return;
  }
  if (MODE === "open") {
    api().pagingLocked = false;
    api().follow = true;
    api().awaitingReplyReveal = false;
    keepSnappingToBottom(FOLLOW_SNAP_FRAMES);
    startEnsureScrollDown();
    return;
  }
  if (MODE === "prepend") {
    api().pagingLocked = false;
    // Older rows are inserted above the current viewport. Restore the old
    // reading position using the captured stable height delta; repeated
    // frames absorb Streamlit's late layout of markdown and attachments.
    api().snapping = true;
    restorePrependedViewport(FOLLOW_SNAP_FRAMES);
    api().snapping = false;
    startEnsureScrollDown();
    return;
  }
  if (MODE === "settle") {
    api().pagingLocked = false;
    syncFollowFromViewport();
    startEnsureScrollDown();
    return;
  }
  if (MODE === "reply") {
    api().pagingLocked = false;
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
  api().pagingLocked = false;
  if (shouldRevealReply()) {
    keepRevealingCoachReply(FOLLOW_SNAP_FRAMES);
  }
  startEnsureScrollDown();
})();
</script>
"""
    script = (
        script.replace("__CD_SYNC_TOKEN__", str(sync_token))
        .replace("__CD_MODE__", repr(cleaned))
        .replace("__CD_NEAR_BOTTOM__", str(int(NEAR_BOTTOM_PX)))
        .replace(
            "__CD_SCROLL_CONTROL_THRESHOLD__",
            str(int(SCROLL_CONTROL_THRESHOLD_PX)),
        )
        .replace("__CD_FOLLOW_FRAMES__", str(int(FOLLOW_SNAP_FRAMES)))
        .replace("__CD_ENSURE_FRAMES__", str(int(SCROLL_DOWN_ENSURE_FRAMES)))
    )
    components.html(wrap_component_html(script), height=0, width=0)
