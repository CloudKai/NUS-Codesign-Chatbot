"""Between-column drag resize for the notebook workspace.

Injects a small browser script that sizes the Gemini-style left nav (fixed px)
and draws drag handles among center / Sources / Thinking Path. Collapse and
Library visibility live in ``st.session_state``. Prefer importing from
``ui.layout``.
"""

from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as components

# Center, Sources, Thinking Path (nav is fixed px, not stored).
DEFAULT_WORKSPACE_WIDTHS: tuple[float, float, float] = (2.35, 1.05, 1.05)
_MIN_RATIO = 0.18
_COLLAPSED_RATIO = 0.08
_RAIL_WIDTH_PX = 42
_NAV_EXPANDED_PX = 260
_NAV_COLLAPSED_PX = 72
_STORAGE_KEY = "cd_workspace_column_widths_v2"


def _normalize_widths(widths: list[float]) -> list[float]:
    """Clamp and renormalize three positive column ratios."""
    values = [max(float(width), _MIN_RATIO) for width in widths[:3]]
    while len(values) < 3:
        values.append(_MIN_RATIO)
    total = sum(values) or 1.0
    return [round(value / total * 4.45, 4) for value in values]


def get_workspace_widths() -> list[float]:
    """Return center / Sources / Thinking Path ratios for ``st.columns``."""
    raw = st.session_state.get("workspace_column_widths")
    if isinstance(raw, (list, tuple)) and len(raw) == 3:
        try:
            return _normalize_widths([float(item) for item in raw])
        except (TypeError, ValueError):
            pass
    return list(DEFAULT_WORKSPACE_WIDTHS)


def nav_collapsed() -> bool:
    """Return whether the left chat nav rail is icon-only."""
    return bool(st.session_state.get("workspace_nav_collapsed", False))


def set_nav_collapsed(collapsed: bool) -> None:
    """Persist left-nav collapse for the session."""
    st.session_state["workspace_nav_collapsed"] = bool(collapsed)


def library_open() -> bool:
    """Return whether the Sources (Library) column is visible."""
    return not side_panel_collapsed("sources")


def set_library_open(open_: bool) -> None:
    """Show or fully hide Sources. Hidden Library leaves no skinny rail."""
    set_side_panel_collapsed("sources", not bool(open_))


def side_panel_collapsed(side: str) -> bool:
    """Return whether Thinking Path (``studio``) or Sources is collapsed/hidden.

    Sources collapsed means Library is off (column fully hidden). Studio
    collapsed still shows a narrow expand rail.
    """
    key = f"workspace_{side}_collapsed"
    return bool(st.session_state.get(key, False))


def set_side_panel_collapsed(side: str, collapsed: bool) -> None:
    """Persist Thinking Path / Sources collapse state for the session."""
    st.session_state[f"workspace_{side}_collapsed"] = bool(collapsed)


def effective_column_widths() -> list[float]:
    """Return ``[nav, center, sources, studio]`` ratios for ``st.columns``.

    Nav weights are placeholders; the resize script forces fixed pixel widths.
    When Library is closed, Sources weight is near-zero (no rail).
    """
    center, sources, studio = get_workspace_widths()
    nav = 0.22 if nav_collapsed() else 0.72
    if side_panel_collapsed("studio"):
        freed = max(studio - _COLLAPSED_RATIO, 0.0)
        studio = _COLLAPSED_RATIO
        center += freed
    if side_panel_collapsed("sources"):
        center += sources
        sources = 0.001
    return [
        round(nav, 4),
        round(center, 4),
        round(sources, 4),
        round(studio, 4),
    ]


def sync_workspace_column_resize() -> None:
    """Apply nav fixed widths and drag handles among open workspace panels."""
    stored = get_workspace_widths()
    studio_collapsed = side_panel_collapsed("studio")
    sources_hidden = side_panel_collapsed("sources")
    nav_is_collapsed = nav_collapsed()
    components.html(
        f"""
<script>
(() => {{
  const STORED = {json.dumps(stored)};
  const MIN_RATIO = {_MIN_RATIO};
  const RAIL_PX = {_RAIL_WIDTH_PX};
  const NAV_EXPANDED_PX = {_NAV_EXPANDED_PX};
  const NAV_COLLAPSED_PX = {_NAV_COLLAPSED_PX};
  const STORAGE_KEY = {_STORAGE_KEY!r};
  const STUDIO_COLLAPSED = {str(studio_collapsed).lower()};
  const SOURCES_HIDDEN = {str(sources_hidden).lower()};
  const NAV_COLLAPSED = {str(nav_is_collapsed).lower()};
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

  function classify(column) {{
    if (
      column.querySelector(".st-key-nav_panel") ||
      column.querySelector(".st-key-nav_rail")
    ) {{
      return "nav";
    }}
    if (
      column.querySelector(".st-key-chat_panel") ||
      column.querySelector(".st-key-search_panel")
    ) {{
      return "center";
    }}
    if (
      column.querySelector(".st-key-sources_panel") ||
      column.querySelector(".st-key-sources_hidden")
    ) {{
      return "sources";
    }}
    if (
      column.querySelector(".st-key-studio_rail") ||
      column.querySelector(".st-key-studio_panel")
    ) {{
      return "studio";
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
      if (columns.length < 4) continue;
      const roles = columns.map(classify);
      if (
        roles.includes("nav") &&
        roles.includes("center") &&
        roles.includes("sources") &&
        roles.includes("studio")
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
      "display",
    ].forEach((prop) => column.style.removeProperty(prop));
    column.classList.remove("cd-col-rail", "cd-col-nav", "cd-col-hidden");
  }}

  function setFixed(column, px, className) {{
    column.classList.add(className);
    column.style.setProperty("flex", "0 0 " + px + "px", "important");
    column.style.setProperty("width", px + "px", "important");
    column.style.setProperty("min-width", px + "px", "important");
    column.style.setProperty("max-width", px + "px", "important");
  }}

  function setHidden(column) {{
    column.classList.add("cd-col-hidden");
    column.style.setProperty("flex", "0 0 0px", "important");
    column.style.setProperty("width", "0px", "important");
    column.style.setProperty("min-width", "0px", "important");
    column.style.setProperty("max-width", "0px", "important");
    column.style.setProperty("display", "none", "important");
  }}

  function setFlex(column, grow) {{
    column.classList.remove("cd-col-rail", "cd-col-nav", "cd-col-hidden");
    column.style.setProperty("flex-grow", String(grow), "important");
    column.style.setProperty("flex-shrink", "1", "important");
    column.style.setProperty("flex-basis", "0px", "important");
    column.style.setProperty("width", "auto", "important");
    column.style.setProperty("min-width", "0", "important");
    column.style.setProperty("max-width", "none", "important");
    column.style.removeProperty("display");
  }}

  function applyLayout(columns, roles, ratios) {{
    const byRole = {{}};
    roles.forEach((role, index) => {{
      byRole[role] = {{ column: columns[index], ratio: ratios[index], index }};
    }});

    Object.values(byRole).forEach((item) => clearSizing(item.column));

    setFixed(
      byRole.nav.column,
      NAV_COLLAPSED ? NAV_COLLAPSED_PX : NAV_EXPANDED_PX,
      "cd-col-nav"
    );

    let centerGrow = byRole.center.ratio;
    let sourcesGrow = byRole.sources.ratio;
    let studioGrow = byRole.studio.ratio;

    if (SOURCES_HIDDEN) {{
      setHidden(byRole.sources.column);
      sourcesGrow = 0;
    }}
    if (STUDIO_COLLAPSED) {{
      setFixed(byRole.studio.column, RAIL_PX, "cd-col-rail");
      studioGrow = 0;
    }}

    const openTotal = centerGrow + sourcesGrow + studioGrow || 1;
    setFlex(byRole.center.column, centerGrow / openTotal);
    if (!SOURCES_HIDDEN) {{
      setFlex(byRole.sources.column, sourcesGrow / openTotal);
    }}
    if (!STUDIO_COLLAPSED) {{
      setFlex(byRole.studio.column, studioGrow / openTotal);
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

    // Ratios are center/sources/studio only (stored length 3).
    const ratios = readStored();
    const layoutRatios = roles.map((role) => {{
      if (role === "center") return ratios[0];
      if (role === "sources") return ratios[1];
      if (role === "studio") return ratios[2];
      return 0;
    }});
    applyLayout(columns, roles, layoutRatios);
    writeStored(ratios);
    win.dispatchEvent(new Event("resize"));

    const openPairs = [];
    for (let i = 0; i < roles.length - 1; i += 1) {{
      const left = roles[i];
      const right = roles[i + 1];
      if (left === "nav" || right === "nav") continue;
      if (left === "sources" && SOURCES_HIDDEN) continue;
      if (right === "sources" && SOURCES_HIDDEN) continue;
      if (left === "studio" && STUDIO_COLLAPSED) continue;
      if (right === "studio" && STUDIO_COLLAPSED) continue;
      openPairs.push(i);
    }}
    if (!openPairs.length) return true;

    let active = null;

    const onMove = (event) => {{
      if (!active) return;
      const delta = event.clientX - active.startX;
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

      const next = active.ratios.slice();
      const pairTotal = next[active.leftStore] + next[active.rightStore];
      next[active.leftStore] = (leftPx / (leftPx + rightPx)) * pairTotal;
      next[active.rightStore] = (rightPx / (leftPx + rightPx)) * pairTotal;
      active.current = next;
      const layoutNext = roles.map((role) => {{
        if (role === "center") return next[0];
        if (role === "sources") return next[1];
        if (role === "studio") return next[2];
        return 0;
      }});
      applyLayout(columns, roles, layoutNext);
      event.preventDefault();
    }};

    const onUp = () => {{
      if (!active) return;
      const finalWidths = (active.current || active.ratios).map((value) =>
        Number(value.toFixed(4))
      );
      if (SOURCES_HIDDEN) finalWidths[1] = ratios[1];
      if (STUDIO_COLLAPSED) finalWidths[2] = ratios[2];
      active = null;
      doc.removeEventListener("mousemove", onMove);
      doc.removeEventListener("mouseup", onUp);
      doc.body.classList.remove("cd-col-resizing");
      writeStored(finalWidths);
    }};

    function storeIndex(role) {{
      if (role === "center") return 0;
      if (role === "sources") return 1;
      if (role === "studio") return 2;
      return -1;
    }}

    openPairs.forEach((index) => {{
      const leftRole = roles[index];
      const rightRole = roles[index + 1];
      const attachToRight = rightRole === "sources";
      const host = attachToRight ? columns[index + 1] : columns[index];
      const handle = doc.createElement("div");
      handle.className = attachToRight
        ? "cd-col-resize-handle cd-col-resize-handle-start"
        : "cd-col-resize-handle";
      handle.setAttribute("role", "separator");
      handle.setAttribute("aria-orientation", "vertical");
      handle.setAttribute("aria-label", "Drag to resize");
      handle.setAttribute("data-tooltip", "Drag to resize");
      if (getComputedStyle(host).position === "static") {{
        host.style.position = "relative";
      }}
      host.appendChild(handle);

      handle.addEventListener("mousedown", (event) => {{
        if (event.button !== 0) return;
        const rowWidth = row.getBoundingClientRect().width;
        const navPx = NAV_COLLAPSED ? NAV_COLLAPSED_PX : NAV_EXPANDED_PX;
        const railCount = STUDIO_COLLAPSED ? 1 : 0;
        const openWidth = Math.max(rowWidth - navPx - railCount * RAIL_PX, 1);
        const leftRect = columns[index].getBoundingClientRect().width;
        const rightRect = columns[index + 1].getBoundingClientRect().width;
        active = {{
          leftStore: storeIndex(leftRole),
          rightStore: storeIndex(rightRole),
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
