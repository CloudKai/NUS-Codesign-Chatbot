"""Keep the chat composer in a Cursor-style card with a footer control row.

``sync_composer_layout`` injects DOM helpers that Streamlit does not expose:
placing the model popover beside the attach control and sizing the composer card.
Call once after rendering the composer widgets. Prefer ``ui.layout.composer_layout``.
"""

from __future__ import annotations

import json
import os

import streamlit.components.v1 as components

from backend.settings import settings


def sync_composer_layout(*, max_file_size_mb: int | None = None) -> None:
    """Pin the model dropdown beside the attach control on the composer footer.

    Also labels the attach control with the student upload size limit because
    Streamlit's chat-input tooltip does not accept custom copy.
    """
    size_mb = int(max_file_size_mb or settings.max_file_size_mb)
    size_hint = f"Max {size_mb} MB per file"
    attach_label = f"Upload or drag and drop files · {size_hint}"
    # This is intentionally opt-in and unavailable in production. It provides
    # browser-only timing counters for diagnosing compositor work; no student
    # text or request data is captured.
    profile_enabled = settings.app_env == "development" and os.getenv(
        "CO_DESIGN_COMPOSER_PROFILE", ""
    ).strip().lower() in {"1", "true", "yes"}
    script = """
<script>
(() => {
  const doc = window.parent.document;
  const win = window.parent;
  const SIZE_HINT = __CD_SIZE_HINT__;
  const ATTACH_LABEL = __CD_ATTACH_LABEL__;
  const PROFILE_ENABLED = __CD_COMPOSER_PROFILE_ENABLED__;
  const now = () => win.performance.now();
  const profile = PROFILE_ENABLED
    ? (win.__cdComposerProfile = win.__cdComposerProfile || {
        inputs: 0,
        input_ms: 0,
        full_apply_calls: 0,
        full_apply_ms: 0,
        textarea_resize_calls: 0,
        textarea_resize_ms: 0,
        textarea_resize_frames: 0,
        animation_frames: 0,
        animation_frame_queue_ms: 0,
        animation_frame_ms: 0,
        mutation_callbacks: 0,
        mutation_ms: 0,
        mutation_records: 0,
        model_menu_mutation_callbacks: 0,
        model_menu_mutation_ms: 0,
        overlay_mutation_callbacks: 0,
        overlay_mutation_ms: 0,
        tooltip_mutation_callbacks: 0,
        tooltip_mutation_ms: 0,
        model_placement_calls: 0,
        textarea_width_callbacks: 0,
        attachment_annotation_calls: 0,
        attachment_tooltip_bind_calls: 0,
        overlay_rewrite_calls: 0,
        native_tooltip_scan_calls: 0,
        selector_calls: 0,
        selector_matches: 0,
        layout_reads: 0,
        layout_writes: 0,
        dom_nodes: doc.querySelectorAll("*").length,
        composer_nodes: 0,
      })
    : null;

  function profileCount(name, amount = 1) {
    if (profile) profile[name] = (profile[name] || 0) + amount;
  }

  function profileSelector(nodes) {
    if (!profile) return nodes;
    profileCount("selector_calls");
    profileCount("selector_matches", nodes ? nodes.length || 1 : 0);
    return nodes;
  }

  if (profile) {
    win.__cdComposerProfileSnapshot = () => ({
      ...profile,
      dom_nodes: doc.querySelectorAll("*").length,
      composer_nodes: (root() || doc.body).querySelectorAll("*").length,
    });
    win.__cdComposerProfileReset = () => {
      for (const [key, value] of Object.entries(profile)) {
        if (typeof value === "number") profile[key] = 0;
      }
      profile.dom_nodes = doc.querySelectorAll("*").length;
      profile.composer_nodes = (root() || doc.body).querySelectorAll("*").length;
      return win.__cdComposerProfileSnapshot();
    };
  }

  function root() {
    return profileSelector(doc.querySelector(".st-key-chat_composer"));
  }

  function chatInput(composer) {
    return composer
      ? profileSelector(composer.querySelector('[data-testid="stChatInput"]'))
      : null;
  }

  function modelSlot(composer) {
    return composer
      ? profileSelector(composer.querySelector(".st-key-composer_model_slot"))
      : null;
  }

  function modelTrigger() {
    return doc.querySelector(
      '.st-key-composer_model_slot [data-testid="stPopoverButton"]'
    );
  }

  function modelMenuBody() {
    const bodies = doc.querySelectorAll('[data-testid="stPopoverBody"]');
    for (const body of bodies) {
      if (body.querySelector('[class*="st-key-composer-model-"]')) return body;
    }
    return null;
  }

  function modelMenuLayer(body) {
    let layer =
      body.closest('[data-baseweb="popover"]') ||
      body.closest('[data-testid="stPopover"]') ||
      body.parentElement;
    while (layer && layer.parentElement && layer.parentElement !== doc.body) {
      const parent = layer.parentElement;
      const style = win.getComputedStyle(parent);
      if (style.position === "fixed" || style.position === "absolute") {
        layer = parent;
        break;
      }
      layer = parent;
    }
    return layer || body;
  }

  function placeModelMenu() {
    const trigger = modelTrigger();
    const body = modelMenuBody();
    if (!trigger || !body) return;

    const rect = trigger.getBoundingClientRect();
    const gap = 6;
    // Pin using the model list height only so opening the side effort
    // flyout does not push the menu upward.
    const modelPane = body.querySelector(".st-key-composer_model_pane");
    const menuHeight = Math.max(
      modelPane
        ? modelPane.getBoundingClientRect().height
        : 0,
      body.querySelector('[class*="st-key-composer-model-"]')
        ? 28
        : 0,
      32
    );
    const top = Math.max(8, rect.top - menuHeight - gap);

    body.style.setProperty("position", "fixed", "important");
    body.style.setProperty("inset", "auto", "important");
    body.style.setProperty("top", top + "px", "important");
    body.style.setProperty("left", rect.left + "px", "important");
    body.style.setProperty("bottom", "auto", "important");
    body.style.setProperty("right", "auto", "important");
    body.style.setProperty("transform", "none", "important");
    body.style.setProperty("margin", "0", "important");
    body.style.setProperty("overflow", "visible", "important");
    body.style.setProperty("z-index", "999", "important");

    const layer = modelMenuLayer(body);
    if (layer && layer !== body) {
      layer.style.setProperty("position", "fixed", "important");
      layer.style.setProperty("inset", "auto", "important");
      layer.style.setProperty("top", top + "px", "important");
      layer.style.setProperty("left", rect.left + "px", "important");
      layer.style.setProperty("bottom", "auto", "important");
      layer.style.setProperty("right", "auto", "important");
      layer.style.setProperty("transform", "none", "important");
      layer.style.setProperty("width", "auto", "important");
      layer.style.setProperty("height", "auto", "important");
      layer.style.setProperty("margin", "0", "important");
      layer.style.setProperty("overflow", "visible", "important");
      layer.style.setProperty("z-index", "999", "important");
    }
  }

  function scheduleMenuPlacement() {
    let frames = 0;
    function tick() {
      placeModelMenu();
      frames += 1;
      if (frames < 10) win.requestAnimationFrame(tick);
    }
    win.requestAnimationFrame(tick);
  }

  function bindModelMenu() {
    const trigger = modelTrigger();
    if (!trigger || trigger.dataset.cdModelMenuBound === "1") return;
    trigger.dataset.cdModelMenuBound = "1";
    trigger.addEventListener("click", scheduleMenuPlacement);
  }

  function watchModelMenu() {
    const body = doc.body;
    if (!body || body.dataset.cdModelMenuWatch === "1") return;
    body.dataset.cdModelMenuWatch = "1";
    const observer = new win.MutationObserver((records) => {
      const started = now();
      profileCount("model_menu_mutation_callbacks");
      const hasModelMenuChange = records.some((record) =>
        Array.from(record.addedNodes).some(
          (node) =>
            node.nodeType === 1 &&
            (node.matches(
              '[data-testid="stPopover"], [data-testid="stPopoverBody"], [data-testid="stPopoverButton"], [class*="st-key-composer-model-"]'
            ) ||
              node.querySelector(
                '[data-testid="stPopover"], [data-testid="stPopoverBody"], [data-testid="stPopoverButton"], [class*="st-key-composer-model-"]'
              ))
        )
      );
      if (hasModelMenuChange) {
        bindModelMenu();
        if (modelMenuBody()) scheduleMenuPlacement();
      }
      if (profile) profileCount("model_menu_mutation_ms", now() - started);
    });
    observer.observe(body, { childList: true, subtree: true });
  }

  function modelPopover(composer) {
    const slot = modelSlot(composer);
    if (!slot) return null;

    const moved = composer.querySelector(
      '[data-testid="stChatInput"] [data-testid="stPopover"]'
    );
    if (moved && !slot.contains(moved)) {
      const anchor =
        slot.querySelector('[data-testid="stElementContainer"]') ||
        slot.querySelector('[data-testid="stVerticalBlock"]') ||
        slot;
      anchor.appendChild(moved);
    }

    return slot.querySelector('[data-testid="stPopover"]');
  }

  function fileUpload(input) {
    return input
      ? profileSelector(
          input.querySelector('[data-testid="stChatInputFileUploadButton"]')
        )
      : null;
  }

  function annotateAttach(input) {
    profileCount("attachment_annotation_calls");
    const attach = fileUpload(input);
    if (attach) attach.setAttribute("data-tooltip", ATTACH_LABEL);
    const btn = attach ? attach.querySelector("button") : null;
    if (btn) {
      btn.setAttribute("aria-label", ATTACH_LABEL);
    }
  }

  function attachTooltipEl() {
    let tip = doc.getElementById("cd-attach-tooltip");
    if (!tip) {
      tip = doc.createElement("div");
      tip.id = "cd-attach-tooltip";
      tip.className = "cd-attach-tooltip";
      tip.setAttribute("role", "tooltip");
      doc.body.appendChild(tip);
    }
    const tokenSource = root() || doc.body;
    const tokens = win.getComputedStyle(tokenSource);
    const bg = tokens.getPropertyValue("--cd-surface").trim() || "#171C22";
    const fg = tokens.getPropertyValue("--cd-text").trim() || "#F2F5F7";
    const border = tokens.getPropertyValue("--cd-border").trim() || "#2A343E";
    tip.textContent = ATTACH_LABEL;
    tip.style.setProperty("position", "fixed", "important");
    tip.style.setProperty("z-index", "10000", "important");
    tip.style.setProperty("padding", ".32rem .55rem", "important");
    tip.style.setProperty("border", "1px solid " + border, "important");
    tip.style.setProperty("border-radius", ".4rem", "important");
    tip.style.setProperty("background", bg, "important");
    tip.style.setProperty("color", fg, "important");
    tip.style.setProperty("-webkit-text-fill-color", fg, "important");
    tip.style.setProperty("font-size", ".75rem", "important");
    tip.style.setProperty("font-weight", "600", "important");
    tip.style.setProperty("line-height", "1.25", "important");
    tip.style.setProperty("white-space", "nowrap", "important");
    tip.style.setProperty("pointer-events", "none", "important");
    tip.style.setProperty("box-shadow", "0 4px 14px rgba(21,32,43,.16)", "important");
    if (!tip.style.left) {
      tip.style.setProperty("left", "-9999px", "important");
      tip.style.setProperty("top", "-9999px", "important");
    }
    if (!tip.classList.contains("cd-attach-tooltip-visible")) {
      tip.style.setProperty("opacity", "0", "important");
      tip.style.setProperty("visibility", "hidden", "important");
    }
    return tip;
  }

  function placeAttachTooltip() {
    const tip = attachTooltipEl();
    const composer = root();
    const attach = fileUpload(chatInput(composer));
    const btn = attach ? attach.querySelector("button") || attach : null;
    if (!btn || doc.body.getAttribute("data-cd-attach-hover") !== "1") {
      tip.classList.remove("cd-attach-tooltip-visible");
      tip.style.setProperty("opacity", "0", "important");
      tip.style.setProperty("visibility", "hidden", "important");
      return;
    }
    const rect = btn.getBoundingClientRect();
    const tipWidth = Math.max(tip.offsetWidth, 1);
    const tipHeight = Math.max(tip.offsetHeight, 1);
    const left = Math.max(
      8,
      Math.min(
        rect.left + rect.width / 2 - tipWidth / 2,
        win.innerWidth - tipWidth - 8
      )
    );
    const top = Math.max(8, rect.top - tipHeight - 8);
    tip.style.setProperty("left", left + "px", "important");
    tip.style.setProperty("top", top + "px", "important");
    tip.classList.add("cd-attach-tooltip-visible");
    tip.style.setProperty("opacity", "1", "important");
    tip.style.setProperty("visibility", "visible", "important");
  }

  let attachTipTimer = 0;
  function showAttachTooltip() {
    doc.body.setAttribute("data-cd-attach-hover", "1");
    win.clearTimeout(attachTipTimer);
    attachTipTimer = win.setTimeout(placeAttachTooltip, 450);
  }

  function hideAttachTooltip() {
    win.clearTimeout(attachTipTimer);
    doc.body.removeAttribute("data-cd-attach-hover");
    placeAttachTooltip();
  }

  function bindAttachTooltip(input) {
    profileCount("attachment_tooltip_bind_calls");
    const attach = fileUpload(input);
    if (!attach) return;
    attachTooltipEl();
    if (attach.dataset.cdAttachTipBound === "1") return;
    attach.dataset.cdAttachTipBound = "1";
    attach.addEventListener("pointerenter", showAttachTooltip);
    attach.addEventListener("pointerleave", hideAttachTooltip);
    attach.addEventListener("focusin", showAttachTooltip);
    attach.addEventListener("focusout", hideAttachTooltip);
  }

  function hideNativeUploadTooltips() {
    profileCount("native_tooltip_scan_calls");
    const nodes = doc.querySelectorAll('[data-testid="stTooltipContent"]');
    for (const node of nodes) {
      const text = (node.textContent || "").trim();
      if (!text.startsWith("Upload or drag and drop files")) continue;
      const layer =
        node.closest('[data-baseweb="tooltip"]') ||
        node.closest('[role="tooltip"]') ||
        node.parentElement ||
        node;
      layer.style.setProperty("display", "none", "important");
      layer.style.setProperty("visibility", "hidden", "important");
      layer.style.setProperty("opacity", "0", "important");
    }
  }

  function rewriteDropOverlay() {
    profileCount("overlay_rewrite_calls");
    const nodes = doc.querySelectorAll(
      '.st-key-chat_composer [data-testid="stChatInput"] *'
    );
    for (const node of nodes) {
      if (node.childElementCount > 0) continue;
      const text = (node.textContent || "").trim();
      if (text === "Drag and drop files here") {
        node.textContent = ["Drag and drop files here", SIZE_HINT].join("\\n");
        node.style.setProperty("white-space", "pre-line", "important");
        node.style.setProperty("text-align", "center", "important");
      }
    }
  }

  function placeModel(composer, input) {
    profileCount("model_placement_calls");
    const popover = modelPopover(composer);
    const attach = fileUpload(input);
    const attachBtn = attach ? attach.querySelector("button") || attach : null;
    if (!popover || !attachBtn) return;

    const composerRect = composer.getBoundingClientRect();
    const attachRect = attachBtn.getBoundingClientRect();
    const chipHeight = Math.max(popover.getBoundingClientRect().height || 24, 24);
    const chipWidth = Math.min(
      Math.max(popover.getBoundingClientRect().width || 80, 68),
      152
    );

    const left = attachRect.right - composerRect.left + 10;
    const bottom =
      composerRect.bottom -
      attachRect.bottom +
      (attachRect.height - chipHeight) / 2;
    const maxLeft = composerRect.width - chipWidth - 56;
    const clampedLeft = Math.max(34, Math.min(left, maxLeft));

    popover.classList.add("cd-model-placed");
    popover.style.setProperty("position", "absolute", "important");
    popover.style.setProperty("left", clampedLeft + "px", "important");
    popover.style.setProperty("bottom", bottom + "px", "important");
    popover.style.setProperty("top", "auto", "important");
    popover.style.setProperty("right", "auto", "important");
    popover.style.setProperty("margin", "0", "important");
    popover.style.setProperty("transform", "none", "important");
    popover.style.setProperty("z-index", "45", "important");
    popover.style.setProperty("width", "max-content", "important");
    popover.style.setProperty("max-width", "14rem", "important");
    popover.style.setProperty("min-width", "max-content", "important");
    popover.style.setProperty("pointer-events", "auto", "important");
    popover.style.setProperty("white-space", "nowrap", "important");
    popover.style.setProperty("opacity", "1", "important");
    popover.style.setProperty("visibility", "visible", "important");
  }

  function textShells(textarea) {
    const shells = [];
    let node = textarea.parentElement;
    for (let depth = 0; depth < 5 && node; depth += 1) {
      const testId = node.getAttribute("data-testid") || "";
      if (testId === "stChatInput") break;
      const isTextShell =
        node.getAttribute("data-baseweb") === "textarea" ||
        node === textarea.parentElement ||
        (!!node.querySelector &&
          !!profileSelector(
            node.querySelector('[data-testid="stChatInputTextArea"], textarea')
          ) &&
          !profileSelector(
            node.querySelector(
              '[data-testid="stChatInputSubmitButton"], [data-testid="stChatInputStopButton"]'
            )
          ));
      if (isTextShell) shells.push(node);
      node = node.parentElement;
    }
    return shells;
  }

  const textareaStates = new WeakMap();
  const inputTextareas = new WeakMap();
  let textareaWidthObserver = null;

  function measurementMirror() {
    let mirror = win.__cdComposerTextareaMeasurementMirror;
    if (mirror && mirror.isConnected) return mirror;
    mirror = doc.createElement("div");
    mirror.id = "cd-composer-textarea-measurement";
    mirror.setAttribute("aria-hidden", "true");
    mirror.style.setProperty("position", "fixed", "important");
    mirror.style.setProperty("left", "-10000px", "important");
    mirror.style.setProperty("top", "0", "important");
    mirror.style.setProperty("visibility", "hidden", "important");
    mirror.style.setProperty("pointer-events", "none", "important");
    mirror.style.setProperty("contain", "layout style paint", "important");
    mirror.style.setProperty("height", "auto", "important");
    mirror.style.setProperty("max-height", "none", "important");
    mirror.style.setProperty("overflow", "visible", "important");
    mirror.style.setProperty("white-space", "pre-wrap", "important");
    mirror.style.setProperty("overflow-wrap", "break-word", "important");
    mirror.style.setProperty("word-break", "break-word", "important");
    doc.body.appendChild(mirror);
    win.__cdComposerTextareaMeasurementMirror = mirror;
    return mirror;
  }

  function textareaState(textarea, refreshMetrics = false) {
    let state = textareaStates.get(textarea);
    if (!state) {
      state = {
        shells: [],
        minHeight: 0,
        maxHeight: 0,
        width: 0,
        inputWidth: 0,
        appliedState: null,
        metricsDirty: true,
      };
      textareaStates.set(textarea, state);
    }
    if (refreshMetrics || state.metricsDirty) {
      const styles = win.getComputedStyle(textarea);
      profileCount("layout_reads");
      const fontSize = parseFloat(styles.fontSize) || 15.2;
      const lineHeight = parseFloat(styles.lineHeight) || fontSize * 1.45;
      const padY =
        (parseFloat(styles.paddingTop) || 0) +
        (parseFloat(styles.paddingBottom) || 0);
      const configuredMin = parseFloat(styles.minHeight) || 0;
      const configuredMax = parseFloat(styles.maxHeight) || 0;
      state.minHeight = Math.max(lineHeight + padY, configuredMin);
      state.maxHeight = Math.max(
        state.minHeight,
        configuredMax || lineHeight * 5 + padY
      );
      state.width = Math.max(textarea.getBoundingClientRect().width, 1);
      profileCount("layout_reads");
      state.shells = textShells(textarea);

      const mirror = measurementMirror();
      mirror.style.setProperty("width", state.width + "px", "important");
      mirror.style.setProperty("box-sizing", styles.boxSizing, "important");
      mirror.style.setProperty("font", styles.font, "important");
      mirror.style.setProperty("letter-spacing", styles.letterSpacing, "important");
      mirror.style.setProperty("line-height", styles.lineHeight, "important");
      mirror.style.setProperty("padding", styles.padding, "important");
      mirror.style.setProperty("border", styles.border, "important");
      state.metricsDirty = false;
      state.appliedState = null;
    }
    return state;
  }

  function invalidateTextareaLayout(textarea) {
    const state = textareaStates.get(textarea);
    if (state) state.appliedState = null;
    if (textarea) delete textarea.dataset.cdComposerSizeState;
  }

  let applyFrame = 0;
  let resizeFrame = 0;
  let modelPlacementFrame = 0;
  let pendingTextarea = null;
  let pendingTextareaMetricsRefresh = false;

  function scheduleApply() {
    if (applyFrame) return;
    const queuedAt = now();
    applyFrame = win.requestAnimationFrame(() => {
      applyFrame = 0;
      const started = now();
      apply();
      if (profile) {
        profileCount("animation_frames");
        profileCount("animation_frame_queue_ms", now() - queuedAt);
        profileCount("animation_frame_ms", now() - started);
      }
    });
  }

  function scheduleModelPlacement(composer, input) {
    if (modelPlacementFrame) return;
    modelPlacementFrame = win.requestAnimationFrame(() => {
      modelPlacementFrame = 0;
      placeModel(composer, input);
    });
  }

  function scheduleTextareaResize(textarea, refreshMetrics = false) {
    if (!textarea) return;
    pendingTextarea = textarea;
    pendingTextareaMetricsRefresh = pendingTextareaMetricsRefresh || refreshMetrics;
    if (resizeFrame) return;
    const queuedAt = now();
    resizeFrame = win.requestAnimationFrame(() => {
      resizeFrame = 0;
      const started = now();
      const currentTextarea = pendingTextarea;
      const refresh = pendingTextareaMetricsRefresh;
      pendingTextarea = null;
      pendingTextareaMetricsRefresh = false;
      if (currentTextarea && currentTextarea.isConnected && !currentTextarea.disabled) {
        capTextarea(currentTextarea, refresh);
      }
      if (profile) {
        profileCount("textarea_resize_frames");
        profileCount("animation_frames");
        profileCount("animation_frame_queue_ms", now() - queuedAt);
        profileCount("animation_frame_ms", now() - started);
      }
    });
  }

  function observeTextareaWidth(textarea) {
    if (typeof win.ResizeObserver !== "function" || !textarea) return;
    const input = textarea.closest('[data-testid="stChatInput"]');
    if (!input) return;
    inputTextareas.set(input, textarea);
    if (!textareaWidthObserver) {
      textareaWidthObserver = new win.ResizeObserver((entries) => {
        for (const entry of entries) {
          const observedTextarea = inputTextareas.get(entry.target);
          if (!observedTextarea || !observedTextarea.isConnected) continue;
          const state = textareaStates.get(observedTextarea);
          const width = Math.max(entry.contentRect.width, 1);
          profileCount("textarea_width_callbacks");
          if (state && Math.abs(state.inputWidth - width) < 0.5) continue;
          if (state) {
            state.inputWidth = width;
            state.metricsDirty = true;
          }
          scheduleTextareaResize(observedTextarea, true);
        }
      });
    }
    if (textarea.dataset.cdComposerWidthObserved === "1") return;
    textarea.dataset.cdComposerWidthObserved = "1";
    textareaWidthObserver.observe(input);
  }

  function capTextarea(textarea, refreshMetrics = false) {
    const started = now();
    profileCount("textarea_resize_calls");
    const state = textareaState(textarea, refreshMetrics);
    const mirror = measurementMirror();
    // Measure in the isolated mirror so a shortened draft can shrink without
    // resetting the live textarea to `auto` on every keystroke.
    mirror.textContent = textarea.value || "\u200b";
    const measured = Math.max(mirror.scrollHeight, state.minHeight);
    profileCount("layout_reads");
    const nextHeight = Math.min(
      Math.max(measured, state.minHeight),
      state.maxHeight
    );
    const needsScroll = measured > state.maxHeight;
    const nextState = nextHeight + ":" + (needsScroll ? "scroll" : "hidden");

    const changed = state.appliedState !== nextState;
    if (changed) {
      state.appliedState = nextState;
      textarea.dataset.cdComposerSizeState = nextState;
      textarea.style.setProperty("height", nextHeight + "px", "important");
      textarea.style.setProperty(
        "overflow-y",
        needsScroll ? "auto" : "hidden",
        "important"
      );
      for (const shell of state.shells) {
        shell.style.setProperty("height", nextHeight + "px", "important");
        shell.style.setProperty("max-height", state.maxHeight + "px", "important");
        shell.style.setProperty("overflow", "hidden", "important");
      }
      profileCount("layout_writes", 2 + state.shells.length * 3);
    }
    if (profile) profileCount("textarea_resize_ms", now() - started);
    return changed;
  }

  function clearStoppedInflightUi() {
    const inflight = doc.querySelector(".st-key-chat_inflight");
    if (inflight) inflight.classList.remove("cd-turn-stopped");
  }

  function hideStoppedInflightUi() {
    // Native Streamlit Stop interrupts the script, but cannot retract output
    // that has already been rendered during that script run. Mark only the
    // transient in-flight region; persisted history remains authoritative.
    const inflight = doc.querySelector(".st-key-chat_inflight");
    if (inflight) inflight.classList.add("cd-turn-stopped");
  }

  function bindNativeStopCleanup(input) {
    if (!input || input.dataset.cdNativeStopCleanupBound === "1") return;
    input.dataset.cdNativeStopCleanupBound = "1";
    // Delegate from the stable composer root because Streamlit changes the
    // same button node from Send to Stop. The native click must still reach
    // Streamlit, which owns cancellation of the current script run.
    input.addEventListener(
      "click",
      (event) => {
        const target = event.target;
        const stop = target && target.closest
          ? target.closest('[data-testid="stChatInputStopButton"]')
          : null;
        if (stop && input.contains(stop)) {
          hideStoppedInflightUi();
          return;
        }
        const submit = target && target.closest
          ? target.closest('[data-testid="stChatInputSubmitButton"]')
          : null;
        if (submit && input.contains(submit)) {
          clearStoppedInflightUi();
          // This capture handler runs before Streamlit swaps Send to Stop.
          // Queue the existing coalesced pass now so the next paint sees the
          // busy control even if the later attribute mutation is skipped when
          // a native Stop previously ended the script run.
          scheduleApply();
        }
      },
      true
    );
  }

  function apply() {
    const started = now();
    profileCount("full_apply_calls");
    const composer = root();
    const input = chatInput(composer);
    if (!composer || !input) return false;
    composer.classList.add("cd-composer-card");
    input.classList.add("cd-composer-card");
    const textarea = input.querySelector('[data-testid="stChatInputTextArea"], textarea');
    bindNativeStopCleanup(input);
    observeTextareaWidth(textarea);
    if (textarea && !textarea.disabled) capTextarea(textarea, true);
    annotateAttach(input);
    bindAttachTooltip(input);
    rewriteDropOverlay();
    hideNativeUploadTooltips();
    if (doc.body.getAttribute("data-cd-attach-hover") === "1") {
      placeAttachTooltip();
    }
    scheduleModelPlacement(composer, input);
    if (profile) profileCount("full_apply_ms", now() - started);
    return true;
  }

  function bind() {
    const composer = root();
    const input = chatInput(composer);
    const textarea = input
      ? input.querySelector('[data-testid="stChatInputTextArea"], textarea')
      : null;
    if (!composer || !input || !textarea) return false;
    if (profile) profile.composer_nodes = composer.querySelectorAll("*").length;

    if (composer.dataset.cdComposerBound === "1") {
      observeTextareaWidth(textarea);
      apply();
      return true;
    }
    composer.dataset.cdComposerBound = "1";
    bindNativeStopCleanup(input);

    const onComposerDraft = (event) => {
      const started = now();
      const target = event.target;
      if (!target || !target.closest) return;
      const textarea = target.closest(
        '[data-testid="stChatInputTextArea"], textarea'
      );
      if (!textarea) {
        return;
      }
      profileCount("inputs");
      // Ordinary typing only needs the capped textarea measurement. Running
      // the attachment/model/tooltip layout routine here makes its cost grow
      // with the rest of the notebook DOM.
      scheduleTextareaResize(textarea);
      if (profile) profileCount("input_ms", now() - started);
    };
    composer.addEventListener("input", onComposerDraft, true);
    composer.addEventListener("change", onComposerDraft, true);
    composer.addEventListener(
      "paste",
      (event) => {
        onComposerDraft(event);
      },
      true
    );
    win.addEventListener("resize", () => {
      scheduleApply();
      placeAttachTooltip();
    });
    const observer = new win.MutationObserver((records) => {
      const started = now();
      profileCount("mutation_callbacks");
      profileCount("mutation_records", records.length);
      // Typing changes a textarea value, not its structural controls. Streamlit
      // changes Send to Stop in place, so that requires narrow attribute
      // observation as well as structural file/popover control changes.
      const structural = records.some((record) =>
        Array.from(record.addedNodes).concat(Array.from(record.removedNodes)).some(
          (node) =>
            node.nodeType === 1 &&
            (node.matches(
              '[data-testid="stChatInputFileUploadButton"], [data-testid="stChatInputSubmitButton"], [data-testid="stChatInputStopButton"], [data-testid="stPopover"]'
            ) ||
              node.querySelector(
                '[data-testid="stChatInputFileUploadButton"], [data-testid="stChatInputSubmitButton"], [data-testid="stChatInputStopButton"], [data-testid="stPopover"]'
              ))
        )
      );
      const controlStateChanged = records.some((record) => {
        if (record.type !== "attributes" || record.target.nodeType !== 1) {
          return false;
        }
        if (record.attributeName === "data-testid") {
          const current = record.target.getAttribute("data-testid");
          return (
            current === "stChatInputSubmitButton" ||
            current === "stChatInputStopButton" ||
            record.oldValue === "stChatInputSubmitButton" ||
            record.oldValue === "stChatInputStopButton"
          );
        }
        return (
          record.attributeName === "disabled" &&
          record.target.matches(
            '[data-testid="stChatInputTextArea"], textarea'
          )
        );
      });
      if (structural || controlStateChanged) scheduleApply();
      if (profile) profileCount("mutation_ms", now() - started);
    });
    observer.observe(input, {
      childList: true,
      subtree: true,
      attributes: true,
      attributeOldValue: true,
      attributeFilter: ["data-testid", "disabled"],
    });
    let overlayFrame = 0;
    const overlayObserver = new win.MutationObserver((records) => {
      const started = now();
      profileCount("overlay_mutation_callbacks");
      const hasDropOverlay = records.some((record) =>
        Array.from(record.addedNodes).some(
          (node) =>
            node.nodeType === 1 &&
            (node.textContent || "").includes("Drag and drop files here")
        )
      );
      if (hasDropOverlay) {
        win.cancelAnimationFrame(overlayFrame);
        overlayFrame = win.requestAnimationFrame(rewriteDropOverlay);
      }
      if (profile) profileCount("overlay_mutation_ms", now() - started);
    });
    overlayObserver.observe(input, { childList: true, subtree: true });
    const nativeTipObserver = new win.MutationObserver((records) => {
      const started = now();
      profileCount("tooltip_mutation_callbacks");
      const hasUploadTooltip = records.some((record) =>
        Array.from(record.addedNodes).some(
          (node) =>
            node.nodeType === 1 &&
            (node.matches('[data-testid="stTooltipContent"]') ||
              node.querySelector('[data-testid="stTooltipContent"]'))
        )
      );
      if (hasUploadTooltip) hideNativeUploadTooltips();
      if (profile) profileCount("tooltip_mutation_ms", now() - started);
    });
    nativeTipObserver.observe(doc.body, { childList: true, subtree: true });
    const slot = modelSlot(composer);
    if (slot) observer.observe(slot, { childList: true, subtree: true });
    observeTextareaWidth(textarea);
    bindModelMenu();
    watchModelMenu();
    apply();
    return true;
  }

  function boot() {
    watchModelMenu();
    bindModelMenu();
    if (bind()) return;
    let attempts = 0;
    const timer = win.setInterval(() => {
      attempts += 1;
      if (bind() || attempts > 60) win.clearInterval(timer);
    }, 80);
  }

  boot();
})();
</script>
        """
    components.html(
        script.replace("__CD_SIZE_HINT__", json.dumps(size_hint)).replace(
            "__CD_ATTACH_LABEL__", json.dumps(attach_label)
        ).replace("__CD_COMPOSER_PROFILE_ENABLED__", json.dumps(profile_enabled)),
        height=0,
    )
