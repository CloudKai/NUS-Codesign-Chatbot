"""Keep the chat composer in a Cursor-style card with a footer control row.

``sync_composer_layout`` injects DOM helpers that Streamlit does not expose:
placing the model popover beside the attach control and sizing the composer card.
Call once after rendering the composer widgets. Prefer ``ui.layout.composer_layout``.
"""

from __future__ import annotations

import streamlit.components.v1 as components


def sync_composer_layout() -> None:
    """Pin the model dropdown beside the attach control on the composer footer."""
    components.html(
        """
<script>
(() => {
  const doc = window.parent.document;
  const win = window.parent;

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
    const menuHeight = Math.max(
      body.getBoundingClientRect().height,
      body.offsetHeight,
      body.scrollHeight,
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
    if (doc.body.dataset.cdModelMenuWatch === "1") return;
    doc.body.dataset.cdModelMenuWatch = "1";
    const observer = new win.MutationObserver(() => {
      bindModelMenu();
      if (modelMenuBody()) scheduleMenuPlacement();
    });
    observer.observe(doc.body, { childList: true, subtree: true });
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
    popover.style.setProperty("max-width", "9.5rem", "important");
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
          !node.querySelector('[data-testid="stChatInputSubmitButton"]'));
      if (isTextShell) shells.push(node);
      node = node.parentElement;
    }
    return shells;
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
    if (textarea) capTextarea(textarea);
    win.requestAnimationFrame(() => {
      placeModel(composer, input);
      if (textarea) capTextarea(textarea);
      win.requestAnimationFrame(() => {
        placeModel(composer, input);
        if (textarea) capTextarea(textarea);
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
    win.addEventListener("resize", schedule);
    const observer = new win.MutationObserver(schedule);
    observer.observe(input, { childList: true, subtree: true, characterData: true });
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
        """,
        height=0,
    )
