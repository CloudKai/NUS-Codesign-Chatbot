"""Desktop sizing for the Gemini-style three-region workspace.

Navigation, center, and Thinking Path share one ratio triple persisted in
browser local storage. Both vertical dividers are draggable on desktop.
Collapse state lives in ``st.session_state``.
"""

from __future__ import annotations

import json

import streamlit as st
import streamlit.components.v1 as components

# Navigation | center | Thinking Path (relative flex ratios).
DEFAULT_WORKSPACE_WIDTHS: tuple[float, float, float] = (0.85, 2.5, 1.0)
_MIN_RATIO = 0.2
_COLLAPSED_RATIO = 0.08
_RAIL_WIDTH_PX = 72
_NAV_COLLAPSED_PX = 72
_NAV_MIN_PX = 200
_NAV_MAX_PX = 420
_PAIR_MIN_PX = 220
_STORAGE_KEY = "cd_workspace_column_widths_v4"


def _normalize_widths(widths: list[float]) -> list[float]:
    """Clamp and renormalize the three workspace column ratios."""
    values = [max(float(width), _MIN_RATIO) for width in widths[:3]]
    while len(values) < 3:
        values.append(_MIN_RATIO)
    total = sum(values) or 1.0
    return [round(value / total * 4.35, 4) for value in values]


def get_workspace_widths() -> list[float]:
    """Return nav / center / Thinking Path ratios for ``st.columns``."""
    raw = st.session_state.get("workspace_column_widths")
    if isinstance(raw, (list, tuple)) and len(raw) == 3:
        try:
            return _normalize_widths([float(item) for item in raw])
        except (TypeError, ValueError):
            pass
    # Migrate the prior center/studio-only pair by inserting the default nav.
    if isinstance(raw, (list, tuple)) and len(raw) == 2:
        try:
            center, studio = (float(raw[0]), float(raw[1]))
            return _normalize_widths(
                [DEFAULT_WORKSPACE_WIDTHS[0], center, studio]
            )
        except (TypeError, ValueError):
            pass
    return list(DEFAULT_WORKSPACE_WIDTHS)


def nav_collapsed() -> bool:
    """Return whether the left chat navigation is icon-only."""
    return bool(st.session_state.get("workspace_nav_collapsed", False))


def set_nav_collapsed(collapsed: bool) -> None:
    """Persist left-navigation collapse for the current session."""
    st.session_state["workspace_nav_collapsed"] = bool(collapsed)


def side_panel_collapsed(side: str) -> bool:
    """Return whether the named side panel is collapsed."""
    return bool(st.session_state.get(f"workspace_{side}_collapsed", False))


def set_side_panel_collapsed(side: str, collapsed: bool) -> None:
    """Persist side-panel collapse state for the current session."""
    st.session_state[f"workspace_{side}_collapsed"] = bool(collapsed)


def effective_column_widths() -> list[float]:
    """Return placeholder ratios for navigation, center, and Thinking Path."""
    nav, center, studio = get_workspace_widths()
    if nav_collapsed():
        freed = max(nav - _COLLAPSED_RATIO, 0.0)
        nav = _COLLAPSED_RATIO
        center += freed
    if side_panel_collapsed("studio"):
        freed = max(studio - _COLLAPSED_RATIO, 0.0)
        studio = _COLLAPSED_RATIO
        center += freed
    return [round(nav, 4), round(center, 4), round(studio, 4)]


def sync_workspace_column_resize() -> None:
    """Apply column flex ratios and install both desktop resize handles."""
    stored = get_workspace_widths()
    studio_collapsed = side_panel_collapsed("studio")
    nav_is_collapsed = nav_collapsed()
    components.html(
        f"""
<script>
(() => {{
  const STORED = {json.dumps(stored)};
  const MIN_RATIO = {_MIN_RATIO};
  const RAIL_PX = {_RAIL_WIDTH_PX};
  const NAV_COLLAPSED_PX = {_NAV_COLLAPSED_PX};
  const NAV_MIN_PX = {_NAV_MIN_PX};
  const NAV_MAX_PX = {_NAV_MAX_PX};
  const PAIR_MIN_PX = {_PAIR_MIN_PX};
  const STORAGE_KEY = {_STORAGE_KEY!r};
  const STUDIO_COLLAPSED = {str(studio_collapsed).lower()};
  const NAV_COLLAPSED = {str(nav_is_collapsed).lower()};
  const MOBILE_QUERY = "(max-width: 1050px)";
  const doc = window.parent.document;
  const win = window.parent;

  function writeStored(ratios) {{
    try {{
      win.localStorage.setItem(STORAGE_KEY, JSON.stringify(ratios));
    }} catch (error) {{
      /* Ignore quota and private-mode failures. */
    }}
  }}

  function readStored() {{
    try {{
      const raw = win.localStorage.getItem(STORAGE_KEY);
      if (!raw) {{
        /* Migrate v3 center/studio pairs once. */
        const legacy = win.localStorage.getItem("cd_workspace_column_widths_v3");
        if (legacy) {{
          const parsed = JSON.parse(legacy);
          if (Array.isArray(parsed) && parsed.length === 2) {{
            return [STORED[0], Number(parsed[0]), Number(parsed[1])];
          }}
        }}
        return STORED.slice();
      }}
      const parsed = JSON.parse(raw);
      if (!Array.isArray(parsed) || parsed.length !== 3) return STORED.slice();
      return parsed.map((value) => Number(value));
    }} catch (error) {{
      return STORED.slice();
    }}
  }}

  function classify(column) {{
    if (column.querySelector(".st-key-nav_panel")) return "nav";
    if (
      column.querySelector(".st-key-chat_panel") ||
      column.querySelector(".st-key-search_panel") ||
      column.querySelector(".st-key-sources_panel")
    ) return "center";
    if (
      column.querySelector(".st-key-studio_rail") ||
      column.querySelector(".st-key-studio_panel")
    ) return "studio";
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
      if (roles.includes("nav") && roles.includes("center") && roles.includes("studio")) {{
        return {{ row, columns, roles }};
      }}
    }}
    return null;
  }}

  function clearSizing(column) {{
    [
      "flex", "flex-grow", "flex-shrink", "flex-basis", "width",
      "min-width", "max-width", "display"
    ].forEach((prop) => column.style.removeProperty(prop));
    column.classList.remove("cd-col-rail", "cd-col-nav");
  }}

  function setFixed(column, px, className) {{
    column.classList.add(className);
    column.style.setProperty("flex", "0 0 " + px + "px", "important");
    column.style.setProperty("width", px + "px", "important");
    column.style.setProperty("min-width", px + "px", "important");
    column.style.setProperty("max-width", px + "px", "important");
  }}

  function setFlex(column, grow) {{
    column.classList.remove("cd-col-rail", "cd-col-nav");
    column.style.setProperty("flex-grow", String(grow), "important");
    column.style.setProperty("flex-shrink", "1", "important");
    column.style.setProperty("flex-basis", "0px", "important");
    column.style.setProperty("width", "auto", "important");
    column.style.setProperty("min-width", "0", "important");
    column.style.setProperty("max-width", "none", "important");
  }}

  function setMobile(column, role) {{
    column.classList.remove("cd-col-rail", "cd-col-nav");
    if (role === "nav" || role === "studio") {{
      column.style.setProperty("flex", "0 0 auto", "important");
      column.style.setProperty("width", "min(20.5rem, 88vw)", "important");
      column.style.setProperty("min-width", "0", "important");
      column.style.setProperty("max-width", "88vw", "important");
      return;
    }}
    column.style.setProperty("flex", "1 1 100%", "important");
    column.style.setProperty("width", "100%", "important");
    column.style.setProperty("min-width", "0", "important");
    column.style.setProperty("max-width", "100%", "important");
  }}

  function applyLayout(columns, roles, ratios) {{
    const byRole = {{}};
    roles.forEach((role, index) => {{
      if (role) byRole[role] = columns[index];
    }});
    Object.values(byRole).forEach(clearSizing);

    if (NAV_COLLAPSED) {{
      setFixed(byRole.nav, NAV_COLLAPSED_PX, "cd-col-nav");
    }}
    if (STUDIO_COLLAPSED) {{
      setFixed(byRole.studio, RAIL_PX, "cd-col-rail");
    }}

    if (NAV_COLLAPSED && STUDIO_COLLAPSED) {{
      setFlex(byRole.center, 1);
      return;
    }}
    if (NAV_COLLAPSED) {{
      const total = ratios[1] + ratios[2] || 1;
      setFlex(byRole.center, ratios[1] / total);
      setFlex(byRole.studio, ratios[2] / total);
      return;
    }}
    if (STUDIO_COLLAPSED) {{
      const total = ratios[0] + ratios[1] || 1;
      setFlex(byRole.nav, ratios[0] / total);
      setFlex(byRole.center, ratios[1] / total);
      return;
    }}

    const total = ratios[0] + ratios[1] + ratios[2] || 1;
    setFlex(byRole.nav, ratios[0] / total);
    setFlex(byRole.center, ratios[1] / total);
    setFlex(byRole.studio, ratios[2] / total);
  }}

  function bindHandle(handle, onDown) {{
    handle.addEventListener("mousedown", (event) => {{
      if (event.button !== 0) return;
      onDown(event);
      event.preventDefault();
      event.stopPropagation();
    }});
  }}

  function install() {{
    const found = findWorkspaceColumns();
    if (!found) return false;
    const {{ row, columns, roles }} = found;
    row.querySelectorAll(".cd-col-resize-handle").forEach((node) => node.remove());
    if (getComputedStyle(row).position === "static") row.style.position = "relative";

    if (win.matchMedia(MOBILE_QUERY).matches) {{
      columns.forEach(clearSizing);
      columns.forEach((column, index) => setMobile(column, roles[index]));
      return true;
    }}

    const ratios = readStored();
    applyLayout(columns, roles, ratios);
    writeStored(ratios);

    const nav = columns[roles.indexOf("nav")];
    const center = columns[roles.indexOf("center")];
    const studio = columns[roles.indexOf("studio")];
    if (getComputedStyle(nav).position === "static") nav.style.position = "relative";
    if (getComputedStyle(center).position === "static") center.style.position = "relative";

    let active = null;

    const onMove = (event) => {{
      if (!active) return;
      const delta = event.clientX - active.startX;
      let next = active.ratios.slice();
      if (active.kind === "nav") {{
        let navPx = active.startNav + delta;
        let centerPx = active.startCenter - delta;
        const studioPx = active.startStudio;
        navPx = Math.max(NAV_MIN_PX, Math.min(NAV_MAX_PX, navPx));
        centerPx = active.startNav + active.startCenter - navPx;
        if (centerPx < PAIR_MIN_PX) {{
          centerPx = PAIR_MIN_PX;
          navPx = active.startNav + active.startCenter - centerPx;
          navPx = Math.max(NAV_MIN_PX, Math.min(NAV_MAX_PX, navPx));
          centerPx = active.startNav + active.startCenter - navPx;
        }}
        const total = navPx + centerPx + studioPx || 1;
        const scale = active.ratios[0] + active.ratios[1] + active.ratios[2];
        next = [
          navPx / total * scale,
          centerPx / total * scale,
          studioPx / total * scale,
        ];
      }} else {{
        const navPx = active.startNav;
        let centerPx = active.startCenter + delta;
        let studioPx = active.startStudio - delta;
        if (centerPx < PAIR_MIN_PX) {{
          studioPx -= PAIR_MIN_PX - centerPx;
          centerPx = PAIR_MIN_PX;
        }}
        if (studioPx < PAIR_MIN_PX) {{
          centerPx -= PAIR_MIN_PX - studioPx;
          studioPx = PAIR_MIN_PX;
        }}
        const total = navPx + centerPx + studioPx || 1;
        const scale = active.ratios[0] + active.ratios[1] + active.ratios[2];
        next = [
          navPx / total * scale,
          centerPx / total * scale,
          studioPx / total * scale,
        ];
      }}
      active.current = next;
      applyLayout(columns, roles, next);
      event.preventDefault();
    }};

    const onUp = () => {{
      if (!active) return;
      const finalWidths = (active.current || active.ratios).map((value) =>
        Number(value.toFixed(4))
      );
      active = null;
      doc.removeEventListener("mousemove", onMove);
      doc.removeEventListener("mouseup", onUp);
      doc.body.classList.remove("cd-col-resizing");
      writeStored(finalWidths);
    }};

    function beginDrag(kind, event) {{
      active = {{
        kind,
        startX: event.clientX,
        startNav: nav.getBoundingClientRect().width,
        startCenter: center.getBoundingClientRect().width,
        startStudio: studio.getBoundingClientRect().width,
        ratios: ratios.slice(),
        current: ratios.slice(),
      }};
      doc.body.classList.add("cd-col-resizing");
      doc.addEventListener("mousemove", onMove);
      doc.addEventListener("mouseup", onUp);
    }}

    if (!NAV_COLLAPSED) {{
      const navHandle = doc.createElement("div");
      navHandle.className = "cd-col-resize-handle";
      navHandle.setAttribute("role", "separator");
      navHandle.setAttribute("aria-orientation", "vertical");
      navHandle.setAttribute("aria-label", "Resize navigation");
      navHandle.setAttribute("data-tooltip", "Drag to resize");
      nav.appendChild(navHandle);
      bindHandle(navHandle, (event) => beginDrag("nav", event));
    }}

    if (!STUDIO_COLLAPSED) {{
      const studioHandle = doc.createElement("div");
      studioHandle.className = "cd-col-resize-handle";
      studioHandle.setAttribute("role", "separator");
      studioHandle.setAttribute("aria-orientation", "vertical");
      studioHandle.setAttribute("aria-label", "Resize Thinking Path");
      studioHandle.setAttribute("data-tooltip", "Drag to resize");
      center.appendChild(studioHandle);
      bindHandle(studioHandle, (event) => beginDrag("studio", event));
    }}

    return true;
  }}

  win.__cdWorkspaceLayoutInstall = install;
  if (!win.__cdWorkspaceLayoutResizeBound) {{
    win.addEventListener("resize", () => {{
      win.requestAnimationFrame(() => {{
        const reinstall = win.__cdWorkspaceLayoutInstall;
        if (typeof reinstall === "function") reinstall();
      }});
    }});
    win.__cdWorkspaceLayoutResizeBound = true;
  }}

  if (!install()) {{
    let attempts = 0;
    const timer = win.setInterval(() => {{
      attempts += 1;
      if (install() || attempts > 50) win.clearInterval(timer);
    }}, 80);
  }}
}})();
</script>
        """,
        height=0,
    )
