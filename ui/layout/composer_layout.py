"""Keep the chat composer in a Cursor-style card with a footer control row.

``sync_composer_layout`` injects DOM helpers that Streamlit does not expose:
placing the model popover beside the attach control and sizing the composer card.
Call once after rendering the composer widgets. Prefer ``ui.layout.composer_layout``.
"""

from __future__ import annotations

import json

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
    script = """
<script>
(() => {
  const doc = window.parent.document;
  const win = window.parent;
  const SIZE_HINT = __CD_SIZE_HINT__;
  const ATTACH_LABEL = __CD_ATTACH_LABEL__;

  function root() {
    return doc.querySelector(".st-key-chat_composer");
  }

  function chatInput(composer) {
    return composer ? composer.querySelector('[data-testid="stChatInput"]') : null;
  }

  function modelSlot(composer) {
    return composer ? composer.querySelector(".st-key-composer_model_slot") : null;
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
    const observer = new win.MutationObserver(() => {
      bindModelMenu();
      if (modelMenuBody()) scheduleMenuPlacement();
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
      ? input.querySelector('[data-testid="stChatInputFileUploadButton"]')
      : null;
  }

  function annotateAttach(input) {
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
          !!node.querySelector('[data-testid="stChatInputTextArea"], textarea') &&
          !node.querySelector(
            '[data-testid="stChatInputSubmitButton"], [data-testid="stChatInputStopButton"]'
          ));
      if (isTextShell) shells.push(node);
      node = node.parentElement;
    }
    return shells;
  }

  function isComposerBusy(input, textarea) {
    return !!(
      input.querySelector('[data-testid="stChatInputStopButton"]') ||
      (textarea && textarea.disabled)
    );
  }

  function setBusyComposer(input, textarea, busy) {
    const inner = input.querySelector(":scope > div");
    const hideNodes = [];
    if (textarea) {
      hideNodes.push(textarea);
      let node = textarea.parentElement;
      for (let depth = 0; depth < 5 && node && node !== input; depth += 1) {
        if (
          node.querySelector(
            '[data-testid="stChatInputStopButton"], [data-testid="stChatInputSubmitButton"]'
          )
        ) {
          break;
        }
        hideNodes.push(node);
        node = node.parentElement;
      }
    }
    const attach = fileUpload(input);
    if (busy) {
      input.dataset.cdComposerBusy = "1";
      input.style.setProperty("min-height", "3.05rem", "important");
      input.style.setProperty("height", "auto", "important");
      if (inner) {
        inner.style.setProperty("min-height", "0", "important");
        inner.style.setProperty("height", "auto", "important");
      }
      for (const node of hideNodes) {
        node.style.setProperty("display", "none", "important");
        node.style.setProperty("height", "0", "important");
        node.style.setProperty("min-height", "0", "important");
      }
      if (attach) attach.style.setProperty("display", "none", "important");
      return;
    }
    if (input.dataset.cdComposerBusy !== "1") return;
    delete input.dataset.cdComposerBusy;
    input.style.removeProperty("min-height");
    input.style.removeProperty("height");
    if (inner) {
      inner.style.removeProperty("min-height");
      inner.style.removeProperty("height");
    }
    for (const node of hideNodes) {
      node.style.removeProperty("display");
      node.style.removeProperty("height");
      node.style.removeProperty("min-height");
    }
    if (attach) attach.style.removeProperty("display");
  }

  function capTextarea(textarea) {
    const MAX_ROWS = 5;
    const styles = win.getComputedStyle(textarea);
    const fontSize = parseFloat(styles.fontSize) || 15.2;
    const lineHeight = parseFloat(styles.lineHeight) || fontSize * 1.45;
    const maxHeight = lineHeight * MAX_ROWS;
    const minHeight = lineHeight;
    const shells = textShells(textarea);

    // Collapse first so scrollHeight tracks the current draft, not the old
    // expanded height left behind after deleting a long paste.
    for (const shell of shells) {
      shell.style.setProperty("height", "auto", "important");
      shell.style.setProperty("max-height", maxHeight + "px", "important");
      shell.style.setProperty("overflow", "hidden", "important");
    }
    textarea.style.setProperty("max-height", maxHeight + "px", "important");
    textarea.style.setProperty("height", minHeight + "px", "important");
    textarea.style.setProperty("overflow-y", "hidden", "important");
    void textarea.offsetHeight;

    const measured = Math.max(textarea.scrollHeight, minHeight);
    const nextHeight = Math.min(measured, maxHeight);
    const needsScroll = measured > maxHeight;

    textarea.style.setProperty("height", nextHeight + "px", "important");
    textarea.style.setProperty(
      "overflow-y",
      needsScroll ? "auto" : "hidden",
      "important"
    );
    for (const shell of shells) {
      shell.style.setProperty("height", nextHeight + "px", "important");
      shell.style.setProperty("max-height", maxHeight + "px", "important");
      shell.style.setProperty("overflow", "hidden", "important");
    }
  }

  function apply() {
    const composer = root();
    const input = chatInput(composer);
    if (!composer || !input) return false;
    composer.classList.add("cd-composer-card");
    input.classList.add("cd-composer-card");
    const textarea = input.querySelector('[data-testid="stChatInputTextArea"], textarea');
    const busy = isComposerBusy(input, textarea);
    setBusyComposer(input, textarea, busy);
    if (textarea && !busy) capTextarea(textarea);
    annotateAttach(input);
    bindAttachTooltip(input);
    rewriteDropOverlay();
    hideNativeUploadTooltips();
    if (doc.body.getAttribute("data-cd-attach-hover") === "1") {
      placeAttachTooltip();
    }
    win.requestAnimationFrame(() => {
      const nextBusy = isComposerBusy(input, textarea);
      setBusyComposer(input, textarea, nextBusy);
      placeModel(composer, input);
      annotateAttach(input);
      bindAttachTooltip(input);
      rewriteDropOverlay();
      if (textarea && !nextBusy) capTextarea(textarea);
      win.requestAnimationFrame(() => {
        const laterBusy = isComposerBusy(input, textarea);
        setBusyComposer(input, textarea, laterBusy);
        placeModel(composer, input);
        annotateAttach(input);
        bindAttachTooltip(input);
        rewriteDropOverlay();
        if (textarea && !laterBusy) capTextarea(textarea);
      });
    });
    return true;
  }

  function bind() {
    const composer = root();
    const input = chatInput(composer);
    const textarea = input
      ? input.querySelector('[data-testid="stChatInputTextArea"], textarea')
      : null;
    if (!composer || !input || !textarea) return false;

    if (composer.dataset.cdComposerBound === "1") {
      apply();
      return true;
    }
    composer.dataset.cdComposerBound = "1";

    const schedule = () => win.requestAnimationFrame(apply);
    textarea.addEventListener("input", schedule);
    textarea.addEventListener("change", schedule);
    textarea.addEventListener("paste", () => {
      win.setTimeout(schedule, 0);
      win.setTimeout(schedule, 50);
    });
    win.addEventListener("resize", () => {
      schedule();
      placeAttachTooltip();
    });
    const observer = new win.MutationObserver(schedule);
    observer.observe(input, { childList: true, subtree: true, characterData: true });
    let overlayFrame = 0;
    const overlayObserver = new win.MutationObserver(() => {
      win.cancelAnimationFrame(overlayFrame);
      overlayFrame = win.requestAnimationFrame(rewriteDropOverlay);
    });
    overlayObserver.observe(input, { childList: true, subtree: true });
    const nativeTipObserver = new win.MutationObserver(hideNativeUploadTooltips);
    nativeTipObserver.observe(doc.body, { childList: true, subtree: true });
    const slot = modelSlot(composer);
    if (slot) observer.observe(slot, { childList: true, subtree: true });
    if (typeof win.ResizeObserver === "function") {
      const resizeObserver = new win.ResizeObserver(schedule);
      resizeObserver.observe(input);
      resizeObserver.observe(textarea);
    }
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
        ),
        height=0,
    )
