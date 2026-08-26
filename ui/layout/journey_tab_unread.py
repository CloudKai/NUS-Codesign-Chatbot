"""Watch the Journey tab and clear unread Journey stage-review badges.

Streamlit mounts both tab bodies on every run, so Python cannot know which
tab is visible. This helper watches ``aria-selected`` on the Journey tab
button and POSTs a clear request only when the student selects Journey.
"""

from __future__ import annotations

import json

import streamlit.components.v1 as components


def sync_journey_unread_watch(*, unread: bool, clear_path: str) -> None:
    """Observe Journey-tab selection and clear unread when it becomes active.

    Args:
        unread: Whether the durable Journey unread flag is currently true.
        clear_path: Relative API path such as
            ``/api/v1/threads/{id}/journey-stage-reviews/read``.
    """
    if not unread:
        return
    payload = json.dumps({"path": clear_path})
    components.html(
        f"""
<script>
(() => {{
  const cfg = {payload};
  const root = window.parent.document;
  const markCleared = () => {{
    try {{
      window.parent.__cdJourneyUnreadCleared = true;
    }} catch (error) {{}}
  }};
  const clearUnread = () => {{
    if (window.parent.__cdJourneyUnreadCleared) return;
    markCleared();
    const url = cfg.path;
    fetch(url, {{ method: "POST", credentials: "same-origin" }})
      .catch(() => {{ window.parent.__cdJourneyUnreadCleared = false; }});
  }};
  const findJourneyTab = () => {{
    const tabs = root.querySelectorAll('button[role="tab"]');
    for (const tab of tabs) {{
      const label = (tab.textContent || "").trim();
      if (label.startsWith("Journey")) return tab;
    }}
    return null;
  }};
  const tab = findJourneyTab();
  if (!tab) return;
  let wasSelected = tab.getAttribute("aria-selected") === "true";
  const observer = new MutationObserver(() => {{
    const nowSelected = tab.getAttribute("aria-selected") === "true";
    if (nowSelected && !wasSelected) clearUnread();
    wasSelected = nowSelected;
  }});
  observer.observe(tab, {{ attributes: true, attributeFilter: ["aria-selected"] }});
  tab.addEventListener("click", () => {{
    if (tab.getAttribute("aria-selected") === "true") clearUnread();
  }});
}})();
</script>
        """,
        height=0,
        width=0,
    )
