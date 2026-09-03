"""Browser corner toasts for short-lived Streamlit notifications.

Streamlit ``st.toast`` only accepts whole-second durations and does not expose
slide-in styling. This helper injects a parent-page controller so dismiss
clicks and auto-hide timers survive Streamlit reruns that destroy the
``components.html`` iframe. If that injection fails (Streamlit upgrade,
sandbox, etc.), it falls back to ``st.toast``.
"""

from __future__ import annotations

import json
import logging

import streamlit as st
import streamlit.components.v1 as components

from ui.html_embed import wrap_component_html

DEFAULT_TOAST_DURATION_MS = 3000
_FALLBACK_TOAST_DURATION_S = 3
_CORNER_TOAST_CONTROLLER_VERSION = 2

logger = logging.getLogger(__name__)

# Compiled in the parent window (not the disposable iframe) so click handlers
# and setTimeout callbacks stay valid after Sources/full-app reruns.
_CORNER_TOAST_CONTROLLER_JS = """
(function () {
  const win = window;
  const doc = document;
  const HOST_ID = "cd-corner-toast-host";
  const STYLE_ID = "cd-corner-toast-style";
  const VERSION = 2;
  const CSS = `
      #cd-corner-toast-host {
        position: fixed;
        top: 5.35rem;
        right: 1.15rem;
        z-index: 100000;
        display: flex;
        flex-direction: column;
        gap: 0.55rem;
        pointer-events: none;
      }
      .cd-corner-toast {
        pointer-events: auto;
        min-width: 16.5rem;
        max-width: 24rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.9rem;
        padding: 0.92rem 1.05rem;
        border-radius: 0.85rem;
        background: color-mix(in srgb, var(--cd-accent-soft, #E6F5F3) 72%, var(--cd-surface, #171d27));
        color: var(--cd-text, #f3f5fb);
        border: 1px solid color-mix(in srgb, var(--cd-accent, #0F766E) 42%, var(--cd-border, transparent));
        border-left: 3px solid var(--cd-accent, #0F766E);
        font: 700 0.95rem/1.35 "IBM Plex Sans", system-ui, sans-serif;
        letter-spacing: 0.01em;
        box-shadow:
          var(--cd-shadow, 0 12px 28px rgba(0, 0, 0, 0.34)),
          0 0 0 1px color-mix(in srgb, var(--cd-accent, #0F766E) 10%, transparent);
        transform: translateX(110%);
        opacity: 0;
        animation: cdCornerToastIn 280ms ease-out forwards;
      }
      .cd-corner-toast-body {
        flex: 1 1 auto;
        min-width: 0;
      }
      .cd-corner-toast-close {
        flex: 0 0 auto;
        box-sizing: border-box;
        border: 0;
        background: transparent;
        color: var(--cd-muted, #a8b0bd);
        cursor: pointer;
        font-size: 1.25rem;
        line-height: 1;
        min-width: 2rem;
        min-height: 2rem;
        padding: 0.35rem;
        display: inline-flex;
        align-items: center;
        justify-content: center;
      }
      .cd-corner-toast-close:hover {
        color: var(--cd-text, #f3f5fb);
      }
      .cd-corner-toast.is-leaving {
        animation: cdCornerToastOut 240ms ease-in forwards;
      }
      @keyframes cdCornerToastIn {
        from { transform: translateX(110%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
      }
      @keyframes cdCornerToastOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(110%); opacity: 0; }
      }
    `;

  function ensureStyle() {
    let style = doc.getElementById(STYLE_ID);
    if (!style) {
      style = doc.createElement("style");
      style.id = STYLE_ID;
      doc.head.appendChild(style);
    }
    style.textContent = CSS;
  }

  function ensureHost() {
    let host = doc.getElementById(HOST_ID);
    if (!host) {
      host = doc.createElement("div");
      host.id = HOST_ID;
      doc.body.appendChild(host);
    }
    return host;
  }

  function clearTimeouts(api) {
    (api.timeouts || []).forEach(function (id) {
      win.clearTimeout(id);
    });
    api.timeouts = [];
  }

  function dismiss(toast) {
    if (!toast || toast.dataset.leaving === "1") {
      return;
    }
    toast.dataset.leaving = "1";
    toast.classList.add("is-leaving");
    win.setTimeout(function () {
      if (toast.parentNode) {
        toast.remove();
      }
    }, 250);
  }

  function show(messages, durationMs) {
    const api = win.__cdCornerToasts;
    clearTimeouts(api);
    ensureStyle();
    const host = ensureHost();
    host.replaceChildren();
    messages.forEach(function (message, index) {
      const toast = doc.createElement("div");
      toast.className = "cd-corner-toast";
      toast.setAttribute("role", "status");
      toast.style.animationDelay = index * 80 + "ms";

      const body = doc.createElement("div");
      body.className = "cd-corner-toast-body";
      body.textContent = message;

      const close = doc.createElement("button");
      close.className = "cd-corner-toast-close";
      close.type = "button";
      close.setAttribute("aria-label", "Dismiss");
      close.textContent = "\\u00d7";

      toast.appendChild(body);
      toast.appendChild(close);
      host.prepend(toast);
      const timeoutId = win.setTimeout(function () {
        win.__cdCornerToasts.dismiss(toast);
      }, durationMs + index * 80);
      api.timeouts.push(timeoutId);
    });
  }

  function installClick(api) {
    if (api.clickInstalled) {
      return;
    }
    doc.addEventListener(
      "click",
      function (event) {
        try {
          const raw = event.target;
          const el = raw && raw.closest ? raw : raw && raw.parentElement;
          const closeBtn = el && el.closest && el.closest(".cd-corner-toast-close");
          if (!closeBtn) {
            return;
          }
          const toast = closeBtn.closest(".cd-corner-toast");
          if (!toast) {
            return;
          }
          event.preventDefault();
          win.__cdCornerToasts.dismiss(toast);
        } catch (_err) {}
      },
      true
    );
    api.clickInstalled = true;
  }

  const existing = win.__cdCornerToasts;
  if (
    existing &&
    existing.version === VERSION &&
    typeof existing.show === "function" &&
    typeof existing.dismiss === "function"
  ) {
    return;
  }
  if (existing && typeof existing.clearTimeouts === "function") {
    try {
      existing.clearTimeouts();
    } catch (_err) {}
  }
  const api = {
    version: VERSION,
    timeouts: [],
    clickInstalled: false,
    dismiss: dismiss,
    show: show,
    clearTimeouts: function () {
      clearTimeouts(api);
    },
  };
  win.__cdCornerToasts = api;
  installClick(api);
})();
"""


def show_corner_toasts(
    *messages: str,
    duration_ms: int = DEFAULT_TOAST_DURATION_MS,
) -> None:
    """Show top-right toasts that slide in from the right, then auto-dismiss.

    Args:
        messages: Toast bodies, shown newest on top in the same stack.
        duration_ms: Visible lifetime before the exit animation. Defaults to 3s.
            Ignored by the ``st.toast`` fallback, which uses whole seconds.
    """
    cleaned = [str(message).strip() for message in messages if str(message).strip()]
    if not cleaned:
        return
    safe_duration = max(500, int(duration_ms))
    try:
        _inject_corner_toasts(cleaned, duration_ms=safe_duration)
    except Exception:
        logger.debug("Corner toast injection failed; using st.toast", exc_info=True)
        for message in cleaned:
            st.toast(message, duration=_FALLBACK_TOAST_DURATION_S)


def _corner_toast_iframe_html(messages: list[str], *, duration_ms: int) -> str:
    """Return iframe HTML that boots the parent-window toast controller.

    Args:
        messages: Already-cleaned toast bodies.
        duration_ms: Visible lifetime in milliseconds.

    Returns:
        HTML for ``components.html`` that defines no iframe-owned dismiss
        closures. The parent script owns show, dismiss, timeouts, and click.
    """
    payload = json.dumps(messages)
    controller = json.dumps(_CORNER_TOAST_CONTROLLER_JS)
    version = _CORNER_TOAST_CONTROLLER_VERSION
    return f"""
<script>
(() => {{
  const messages = {payload};
  const durationMs = {duration_ms};
  const parentDoc = window.parent.document;
  const parentWin = window.parent;
  if (!parentWin.__cdCornerToasts || parentWin.__cdCornerToasts.version !== {version}) {{
    const boot = parentDoc.createElement("script");
    boot.textContent = {controller};
    parentDoc.head.appendChild(boot);
  }}
  parentWin.__cdCornerToasts.show(messages, durationMs);
}})();
</script>
"""


def _inject_corner_toasts(messages: list[str], *, duration_ms: int) -> None:
    """Inject parent-page toast DOM. Raises if the component call fails."""
    components.html(
        wrap_component_html(
            _corner_toast_iframe_html(messages, duration_ms=duration_ms)
        ),
        height=0,
        width=0,
    )
