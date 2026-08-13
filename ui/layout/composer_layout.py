"""Keep the chat composer compact while allowing multiline drafts.

``sync_composer_layout`` caps the native Streamlit chat input at five rows,
then enables internal scrolling. Call it once after rendering the composer.
"""

from __future__ import annotations

import json

import streamlit.components.v1 as components


def sync_composer_layout(*, upload_limits_hint: str = "") -> None:
    """Grow the composer and label its native attachment control."""
    encoded_hint = json.dumps(str(upload_limits_hint or ""))
    script = """
<script>
(() => {
  const doc = window.parent.document;
  const win = window.parent;
  const uploadLimitsHint = __UPLOAD_LIMITS_HINT__;
  if (typeof win.__cdComposerLayoutCleanup === "function") {
    try { win.__cdComposerLayoutCleanup(); } catch (_) {}
  }

  let boundComposer = null;
  let boundInput = null;
  let boundTextarea = null;
  let inputHandler = null;
  let pasteHandler = null;
  let mutationObserver = null;
  let resizeObserver = null;
  let bootTimer = null;
  const tooltipTimers = new Set();
  const uploadBindings = [];

  function root() {
    return doc.querySelector(".st-key-chat_composer");
  }

  function chatInput(composer) {
    return composer ? composer.querySelector('[data-testid="stChatInput"]') : null;
  }

  function appendLimitsToTooltip() {
    if (!uploadLimitsHint) return false;
    const tooltips = doc.querySelectorAll(
      '[role="tooltip"], [data-testid="stTooltipContent"]'
    );
    for (const tooltip of [...tooltips].reverse()) {
      if (!tooltip.textContent.includes("Upload or drag and drop files")) continue;
      let limit = tooltip.querySelector(".cd-composer-upload-limit");
      if (!limit) {
        limit = doc.createElement("div");
        limit.className = "cd-composer-upload-limit";
        limit.textContent = uploadLimitsHint;
        limit.style.marginTop = "4px";
        limit.style.paddingTop = "4px";
        limit.style.borderTop = "1px solid rgba(255,255,255,.2)";
        limit.style.fontSize = ".76rem";
        limit.style.opacity = ".82";
        limit.style.whiteSpace = "nowrap";
        tooltip.appendChild(limit);
      }
      return true;
    }
    return false;
  }

  function scheduleTooltipLimits() {
    let attempts = 0;
    const timer = win.setInterval(() => {
      attempts += 1;
      if (appendLimitsToTooltip() || attempts > 15) {
        win.clearInterval(timer);
        tooltipTimers.delete(timer);
      }
    }, 40);
    tooltipTimers.add(timer);
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
    }
  }

  function apply() {
    const composer = root();
    const input = chatInput(composer);
    if (!composer || !input) return false;
    composer.classList.add("cd-composer-card");
    input.classList.add("cd-composer-card");
    const textarea = input.querySelector(
      '[data-testid="stChatInputTextArea"], textarea'
    );
    if (textarea) capTextarea(textarea);
    const uploadTargets = input.querySelectorAll(
      '[data-testid="stChatInputFileUploadButton"], ' +
      '[data-testid="stChatInputFileUploadButton"] button'
    );
    if (uploadLimitsHint) {
      uploadTargets.forEach((target) => {
        // Keep Streamlit's existing tooltip and extend it after it opens.
        // Removing title prevents a second native browser tooltip.
        target.removeAttribute("title");
        if (target.dataset.cdUploadHintBound !== "1") {
          target.dataset.cdUploadHintBound = "1";
          const showLimits = () => scheduleTooltipLimits();
          target.addEventListener("mouseenter", showLimits);
          target.addEventListener("focus", showLimits);
          uploadBindings.push({ target, showLimits });
        }
      });
    }
    return true;
  }

  function bind() {
    const composer = root();
    const input = chatInput(composer);
    const textarea = input
      ? input.querySelector('[data-testid="stChatInputTextArea"], textarea')
      : null;
    if (!composer || !input || !textarea) return false;
    boundComposer = composer;

    if (composer.dataset.cdComposerBound === "1") {
      apply();
      return true;
    }
    composer.dataset.cdComposerBound = "1";

    const schedule = () => win.requestAnimationFrame(apply);
    inputHandler = schedule;
    pasteHandler = () => {
      win.setTimeout(schedule, 0);
      win.setTimeout(schedule, 50);
    };
    boundInput = input;
    boundTextarea = textarea;
    textarea.addEventListener("input", inputHandler);
    textarea.addEventListener("change", inputHandler);
    textarea.addEventListener("paste", pasteHandler);
    win.addEventListener("resize", schedule);
    mutationObserver = new win.MutationObserver(schedule);
    if (input instanceof win.Node) {
      mutationObserver.observe(input, {
        childList: true,
        subtree: true,
        characterData: true
      });
    }
    if (typeof win.ResizeObserver === "function") {
      resizeObserver = new win.ResizeObserver(schedule);
      resizeObserver.observe(input);
      resizeObserver.observe(textarea);
    }
    apply();
    return true;
  }

  function boot() {
    if (bind()) return;
    let attempts = 0;
    bootTimer = win.setInterval(() => {
      attempts += 1;
      if (bind() || attempts > 60) {
        win.clearInterval(bootTimer);
        bootTimer = null;
      }
    }, 80);
  }

  boot();

  win.__cdComposerLayoutCleanup = () => {
    if (bootTimer) {
      win.clearInterval(bootTimer);
      bootTimer = null;
    }
    tooltipTimers.forEach((timer) => win.clearInterval(timer));
    tooltipTimers.clear();
    uploadBindings.forEach(({ target, showLimits }) => {
      target.removeEventListener("mouseenter", showLimits);
      target.removeEventListener("focus", showLimits);
      delete target.dataset.cdUploadHintBound;
    });
    if (mutationObserver) {
      mutationObserver.disconnect();
      mutationObserver = null;
    }
    if (resizeObserver) {
      resizeObserver.disconnect();
      resizeObserver = null;
    }
    if (boundTextarea && inputHandler) {
      boundTextarea.removeEventListener("input", inputHandler);
      boundTextarea.removeEventListener("change", inputHandler);
    }
    if (boundTextarea && pasteHandler) {
      boundTextarea.removeEventListener("paste", pasteHandler);
    }
    if (inputHandler) {
      win.removeEventListener("resize", inputHandler);
    }
    if (boundComposer) {
      delete boundComposer.dataset.cdComposerBound;
    }
    boundComposer = null;
    boundInput = null;
    boundTextarea = null;
    inputHandler = null;
    pasteHandler = null;
  };
})();
</script>
    """.replace("__UPLOAD_LIMITS_HINT__", encoded_hint)
    components.html(
        script,
        height=0,
    )
