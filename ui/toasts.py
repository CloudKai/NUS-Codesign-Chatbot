"""Browser corner toasts for short-lived Streamlit notifications.

Streamlit ``st.toast`` only accepts whole-second durations and does not expose
slide-in styling. This helper injects a small parent-page script so messages can
auto-dismiss after a precise interval without tying timers to a disposable iframe.
"""

from __future__ import annotations

import json

import streamlit.components.v1 as components

DEFAULT_TOAST_DURATION_MS = 2500


def show_corner_toasts(
    *messages: str,
    duration_ms: int = DEFAULT_TOAST_DURATION_MS,
) -> None:
    """Show top-right toasts that slide in from the right, then auto-dismiss.

    Args:
        messages: Toast bodies, shown newest on top in the same stack.
        duration_ms: Visible lifetime before the exit animation. Defaults to 2.5s.
    """
    cleaned = [str(message).strip() for message in messages if str(message).strip()]
    if not cleaned:
        return
    payload = json.dumps(cleaned)
    safe_duration = max(500, int(duration_ms))
    components.html(
        f"""
<script>
(() => {{
  const messages = {payload};
  const durationMs = {safe_duration};
  const parentDoc = window.parent.document;
  const hostId = "cd-corner-toast-host";
  const styleId = "cd-corner-toast-style";

  if (!parentDoc.getElementById(styleId)) {{
    const style = parentDoc.createElement("style");
    style.id = styleId;
    style.textContent = `
      #cd-corner-toast-host {{
        position: fixed;
        top: 1rem;
        right: 1rem;
        z-index: 100000;
        display: flex;
        flex-direction: column;
        gap: 0.55rem;
        pointer-events: none;
      }}
      .cd-corner-toast {{
        pointer-events: auto;
        min-width: 15.5rem;
        max-width: 22rem;
        display: flex;
        align-items: center;
        justify-content: space-between;
        gap: 0.85rem;
        padding: 0.82rem 0.95rem;
        border-radius: 0.85rem;
        background: var(--cd-surface, #171d27);
        color: var(--cd-text, #f3f5fb);
        border: 1px solid var(--cd-border, transparent);
        font: 650 0.9rem/1.35 "IBM Plex Sans", system-ui, sans-serif;
        box-shadow: var(--cd-shadow, 0 12px 28px rgba(0, 0, 0, 0.34));
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
        font-size: 1rem;
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
    parentDoc.head.appendChild(style);
  }}

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
