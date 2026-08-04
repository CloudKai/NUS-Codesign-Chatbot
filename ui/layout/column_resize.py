"""Between-column drag resize for the notebook workspace.

Injects a small browser script that draws drag handles between the Thinking Path,
Chat, and Sources columns. Collapse state and ratios live in ``st.session_state``
and are restored on each render. Prefer importing from ``ui.layout``.
"""

from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as components

DEFAULT_WORKSPACE_WIDTHS: tuple[float, float, float] = (1.05, 2.35, 1.05)
_MIN_RATIO = 0.18
_COLLAPSED_RATIO = 0.08
_RAIL_WIDTH_PX = 42
_STORAGE_KEY = "cd_workspace_column_widths"


def _normalize_widths(widths: list[float]) -> list[float]:
    """Clamp and renormalize three positive column ratios."""
    values = [max(float(width), _MIN_RATIO) for width in widths[:3]]
    while len(values) < 3:
        values.append(_MIN_RATIO)
    total = sum(values) or 1.0
    return [round(value / total * 4.45, 4) for value in values]


def get_workspace_widths() -> list[float]:
    """Return desktop workspace column ratios for ``st.columns``."""
    raw = st.session_state.get("workspace_column_widths")
    if isinstance(raw, (list, tuple)) and len(raw) == 3:
        try:
            return _normalize_widths([float(item) for item in raw])
        except (TypeError, ValueError):
            pass
    return list(DEFAULT_WORKSPACE_WIDTHS)


def side_panel_collapsed(side: str) -> bool:
    """Return whether Thinking Path (``studio``) or Sources is collapsed."""
    key = f"workspace_{side}_collapsed"
    return bool(st.session_state.get(key, False))


def set_side_panel_collapsed(side: str, collapsed: bool) -> None:
    """Persist Thinking Path / Sources collapse state for the session."""
    st.session_state[f"workspace_{side}_collapsed"] = bool(collapsed)


def effective_column_widths() -> list[float]:
    """Return column ratios after applying side-panel collapse."""
    studio, chat, sources = get_workspace_widths()
    if side_panel_collapsed("studio"):
        freed = max(studio - _COLLAPSED_RATIO, 0.0)
        studio = _COLLAPSED_RATIO
        chat += freed
    if side_panel_collapsed("sources"):
        freed = max(sources - _COLLAPSED_RATIO, 0.0)
        sources = _COLLAPSED_RATIO
        chat += freed
    return [round(studio, 4), round(chat, 4), round(sources, 4)]


def sync_workspace_column_resize() -> None:
    """Apply column widths and between-column drag handles.

    Collapsed side columns stay fixed rails. Drag handles remain between any
    two adjacent open panels so resize still works while a side is collapsed.
    """
    stored = get_workspace_widths()
    studio_collapsed = side_panel_collapsed("studio")
    sources_collapsed = side_panel_collapsed("sources")
    components.html(
        f"""
<script>
(() => {{
  const STORED = {json.dumps(stored)};
  const MIN_RATIO = {_MIN_RATIO};
  const RAIL_PX = {_RAIL_WIDTH_PX};
  const STORAGE_KEY = {_STORAGE_KEY!r};
  const STUDIO_COLLAPSED = {str(studio_collapsed).lower()};
  const SOURCES_COLLAPSED = {str(sources_collapsed).lower()};
  const doc = window.parent.document;
  const win = window.parent;

  function writeStored(ratios) {{
    try {{
      win.localStorage.setItem(STORAGE_KEY, JSON.stringify(ratios));
    }} catch (error) {{
      /* ignore quota / private mode */
    }}
  }}

  function readStored() {{
    try {{
      const raw = win.localStorage.getItem(STORAGE_KEY);
      if (!raw) return STORED.slice();
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed) || parsed.length !== 3) return STORED.slice();
      return parsed.map((value) => Number(value));
    }} catch (error) {{
      return STORED.slice();
    }}
  }}

  function isCollapsedRole(role) {{
    return (
      (role === "studio" && STUDIO_COLLAPSED) ||
      (role === "sources" && SOURCES_COLLAPSED)
    );
  }}

  function classify(column) {{
    if (
      column.querySelector(".st-key-studio_rail") ||
      column.querySelector(".st-key-studio_panel")
    ) {{
      return "studio";
    }}
    if (column.querySelector(".st-key-chat_panel")) return "chat";
    if (
      column.querySelector(".st-key-sources_rail") ||
      column.querySelector(".st-key-sources_panel")
    ) {{
      return "sources";
    }}
    return null;
  }}

  function findWorkspaceColumns() {{
    const workspace = doc.querySelector(".st-key-notebook_workspace");
    if (!workspace) return null;
    const rows = workspace.querySelectorAll('[data-testid="stHorizontalBlock"]');
    for (const row of rows) {{
      const columns = Array.from(
        row.querySelectorAll(':scope > [data-testid="stColumn"]')
      );
      if (columns.length < 3) continue;
      const roles = columns.map(classify);
      if (
        roles.includes("studio") &&
        roles.includes("chat") &&
        roles.includes("sources")
      ) {{
        return {{ row, columns, roles }};
      }}
    }}
    return null;
  }}

  function clearSizing(column) {{
    [
      "flex",
      "flex-grow",
      "flex-shrink",
      "flex-basis",
      "width",
      "min-width",
      "max-width",
    ].forEach((prop) => column.style.removeProperty(prop));
    column.classList.remove("cd-col-rail");
  }}

  function setRail(column) {{
    column.classList.add("cd-col-rail");
    column.style.setProperty("flex", "0 0 " + RAIL_PX + "px", "important");
    column.style.setProperty("width", RAIL_PX + "px", "important");
    column.style.setProperty("min-width", RAIL_PX + "px", "important");
    column.style.setProperty("max-width", RAIL_PX + "px", "important");
  }}

  function setFlex(column, grow) {{
    column.classList.remove("cd-col-rail");
    column.style.setProperty("flex-grow", String(grow), "important");
    column.style.setProperty("flex-shrink", "1", "important");
    column.style.setProperty("flex-basis", "0px", "important");
    column.style.setProperty("width", "auto", "important");
    column.style.setProperty("min-width", "0", "important");
    column.style.setProperty("max-width", "none", "important");
  }}

  function applyLayout(columns, roles, ratios) {{
    const byRole = {{}};
    roles.forEach((role, index) => {{
      byRole[role] = {{ column: columns[index], ratio: ratios[index], index }};
    }});

    Object.values(byRole).forEach((item) => clearSizing(item.column));

    let studioGrow = byRole.studio.ratio;
    let chatGrow = byRole.chat.ratio;
    let sourcesGrow = byRole.sources.ratio;

    if (STUDIO_COLLAPSED) {{
      setRail(byRole.studio.column);
      studioGrow = 0;
    }}
    if (SOURCES_COLLAPSED) {{
      setRail(byRole.sources.column);
      sourcesGrow = 0;
    }}

    const openTotal = studioGrow + chatGrow + sourcesGrow || 1;
    if (!STUDIO_COLLAPSED) {{
      setFlex(byRole.studio.column, studioGrow / openTotal);
    }}
    setFlex(byRole.chat.column, chatGrow / openTotal);
    if (!SOURCES_COLLAPSED) {{
      setFlex(byRole.sources.column, sourcesGrow / openTotal);
    }}
  }}

  function install() {{
    const found = findWorkspaceColumns();
    if (!found) return false;
    const {{ row, columns, roles }} = found;

    row.querySelectorAll(".cd-col-resize-handle").forEach((node) => node.remove());
    if (getComputedStyle(row).position === "static") {{
      row.style.position = "relative";
    }}

    const ratios = readStored();
    applyLayout(columns, roles, ratios);
    writeStored(ratios);
    win.dispatchEvent(new Event("resize"));

    const openCount =
      (STUDIO_COLLAPSED ? 0 : 1) + 1 + (SOURCES_COLLAPSED ? 0 : 1);
    if (openCount < 2) return true;

    let active = null;

    const onMove = (event) => {{
      if (!active) return;
      const delta = event.clientX - active.startX;
      const left = active.leftIndex;
      const right = active.rightIndex;
      if (active.openWidth <= 0) return;

      let leftPx = active.startLeftPx + delta;
      let rightPx = active.startRightPx - delta;
      const minPx = Math.max(active.openWidth * MIN_RATIO, 120);
      if (leftPx < minPx) {{
        rightPx -= minPx - leftPx;
        leftPx = minPx;
      }}
      if (rightPx < minPx) {{
        leftPx -= minPx - rightPx;
        rightPx = minPx;
      }}

      const pairTotal = active.ratios[left] + active.ratios[right];
      const next = active.ratios.slice();
      next[left] = (leftPx / (leftPx + rightPx)) * pairTotal;
      next[right] = (rightPx / (leftPx + rightPx)) * pairTotal;
      active.current = next;
      applyLayout(columns, roles, next);
      event.preventDefault();
    }};

    const onUp = () => {{
      if (!active) return;
      const finalWidths = (active.current || active.ratios).map((value) =>
        Number(value.toFixed(4))
      );
      // Keep collapsed panel's remembered width for when it expands again.
      roles.forEach((role, index) => {{
        if (isCollapsedRole(role)) finalWidths[index] = ratios[index];
      }});
      active = null;
      doc.removeEventListener("mousemove", onMove);
      doc.removeEventListener("mouseup", onUp);
      doc.body.classList.remove("cd-col-resizing");
      writeStored(finalWidths);
    }};

    columns.slice(0, -1).forEach((column, index) => {{
      const leftRole = roles[index];
      const rightRole = roles[index + 1];
      if (isCollapsedRole(leftRole) || isCollapsedRole(rightRole)) return;

      const handle = doc.createElement("div");
      handle.className = "cd-col-resize-handle";
      handle.setAttribute("role", "separator");
      handle.setAttribute("aria-orientation", "vertical");
      handle.title = "Drag to resize";
      if (getComputedStyle(column).position === "static") {{
        column.style.position = "relative";
      }}
      column.appendChild(handle);

      handle.addEventListener("mousedown", (event) => {{
        if (event.button !== 0) return;
        const rowWidth = row.getBoundingClientRect().width;
        const railCount =
          (STUDIO_COLLAPSED ? 1 : 0) + (SOURCES_COLLAPSED ? 1 : 0);
        const openWidth = Math.max(rowWidth - railCount * RAIL_PX, 1);
        const leftRect = columns[index].getBoundingClientRect().width;
        const rightRect = columns[index + 1].getBoundingClientRect().width;
        active = {{
          leftIndex: index,
          rightIndex: index + 1,
          startX: event.clientX,
          openWidth,
          startLeftPx: leftRect,
          startRightPx: rightRect,
          ratios: ratios.slice(),
          current: ratios.slice(),
        }};
        doc.body.classList.add("cd-col-resizing");
        doc.addEventListener("mousemove", onMove);
        doc.addEventListener("mouseup", onUp);
        event.preventDefault();
        event.stopPropagation();
      }});
    }});

    return true;
  }}

  function boot() {{
    if (install()) return;
    let attempts = 0;
    const timer = win.setInterval(() => {{
      attempts += 1;
      if (install() || attempts > 50) win.clearInterval(timer);
    }}, 80);
  }}

  boot();
}})();
</script>
        """,
        height=0,
    )
