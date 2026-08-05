"""Browser corner toasts for short-lived Streamlit notifications.

Streamlit ``st.toast`` only accepts whole-second durations and does not expose
slide-in styling. This helper prefers a small parent-page script so messages can
auto-dismiss after a precise interval without tying timers to a disposable
iframe. If that injection fails (Streamlit upgrade, sandbox, etc.), it falls
back to ``st.toast``.
"""

from __future__ import annotations

import json
import logging

import streamlit as st
import streamlit.components.v1 as components

DEFAULT_TOAST_DURATION_MS = 3000
_FALLBACK_TOAST_DURATION_S = 3

logger = logging.getLogger(__name__)


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


def _inject_corner_toasts(messages: list[str], *, duration_ms: int) -> None:
    """Inject parent-page toast DOM. Raises if the component call fails."""
    payload = json.dumps(messages)
    components.html(
        f"""
<script>
(() => {{
  const messages = {payload};
  const durationMs = {duration_ms};
  const parentDoc = window.parent.document;
  const hostId = "cd-corner-toast-host";
  const styleId = "cd-corner-toast-style";

  let style = parentDoc.getElementById(styleId);
  if (!style) {{
    style = parentDoc.createElement("style");
    style.id = styleId;
    parentDoc.head.appendChild(style);
  }}
  style.textContent = `
      #cd-corner-toast-host {{
        position: fixed;
        top: 5.35rem;
        right: 1.15rem;
        z-index: 100000;
        display: flex;
        flex-direction: column;
        gap: 0.55rem;
        pointer-events: none;
      }}
      .cd-corner-toast {{
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
      }}
      .cd-corner-toast-body {{
        flex: 1 1 auto;
        min-width: 0;
      }}
      .cd-corner-toast-close {{
        flex: 0 0 auto;
        border: 0;
        background: transparent;
        color: var(--cd-muted, #a8b0bd);
        cursor: pointer;
        font-size: 1.05rem;
        line-height: 1;
        padding: 0;
      }}
      .cd-corner-toast-close:hover {{
        color: var(--cd-text, #f3f5fb);
      }}
      .cd-corner-toast.is-leaving {{
        animation: cdCornerToastOut 240ms ease-in forwards;
      }}
      @keyframes cdCornerToastIn {{
        from {{ transform: translateX(110%); opacity: 0; }}
        to {{ transform: translateX(0); opacity: 1; }}
      }}
      @keyframes cdCornerToastOut {{
        from {{ transform: translateX(0); opacity: 1; }}
        to {{ transform: translateX(110%); opacity: 0; }}
      }}
    `;

  let host = parentDoc.getElementById(hostId);
  if (!host) {{
    host = parentDoc.createElement("div");
    host.id = hostId;
    parentDoc.body.appendChild(host);
  }} else {{
    host.replaceChildren();
  }}

  /* Timers must live on the parent window. This iframe is torn down on
     Streamlit reruns, which would leave orphaned toasts if we used local timers. */
  const parentWin = window.parent;
  const dismiss = (toast) => {{
    if (!toast || toast.dataset.leaving === "1") {{
      return;
    }}
    toast.dataset.leaving = "1";
    toast.classList.add("is-leaving");
    parentWin.setTimeout(() => toast.remove(), 250);
  }};

  messages.forEach((message, index) => {{
    const toast = parentDoc.createElement("div");
    toast.className = "cd-corner-toast";
    toast.setAttribute("role", "status");
    toast.style.animationDelay = `${{index * 80}}ms`;

    const body = parentDoc.createElement("div");
    body.className = "cd-corner-toast-body";
    body.textContent = message;

    const close = parentDoc.createElement("button");
    close.className = "cd-corner-toast-close";
    close.type = "button";
    close.setAttribute("aria-label", "Dismiss");
    close.textContent = "×";
    close.addEventListener("click", () => dismiss(toast));

    toast.appendChild(body);
    toast.appendChild(close);
    host.prepend(toast);
    parentWin.setTimeout(() => dismiss(toast), durationMs + index * 80);
  }});
}})();
</script>
""",
        height=0,
        width=0,
    )
