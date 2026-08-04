"""Keep the Sources folder list scrollable inside the side panel.

``sync_sources_scroll`` measures the Sources column and assigns a max height to
``.st-key-sources_scroll`` so long libraries scroll without stretching the page.
Prefer ``ui.layout.sources_scroll``.
"""

from __future__ import annotations

import streamlit.components.v1 as components


def sync_sources_scroll() -> None:
    """Size the sources list region and enable vertical scrolling."""
    components.html(
        """
<script>
(() => {
  const doc = window.parent.document;
  const win = window.parent;

  function panel() {
    return doc.querySelector(".st-key-sources_panel");
  }

  function column(panel) {
    return panel?.closest("[data-testid='stColumn']");
  }

  function scrollRoot(panel) {
    return panel.querySelector(".st-key-sources_scroll");
  }

  function scrollTargets(panel) {
    const root = scrollRoot(panel);
    if (!root) return [];
    const targets = new Set([root]);
    const element = root.closest("[data-testid='stElementContainer']");
    if (element) targets.add(element);
    const layoutWrapper = root.closest("[data-testid='stLayoutWrapper']");
    if (layoutWrapper?.querySelector(".st-key-sources_scroll") === root) {
      targets.add(layoutWrapper);
    }
    return [...targets];
  }

  function clearNestedScroll(panel) {
    const root = scrollRoot(panel);
    if (!root) return;
    root
      .querySelectorAll(
        "[data-testid='stVerticalBlock'], [data-testid='stLayoutWrapper'], [data-testid='stElementContainer'], [data-testid='stExpander']"
      )
      .forEach((node) => {
        if (node === root) return;
        node.style.setProperty("height", "auto", "important");
        node.style.setProperty("max-height", "none", "important");
        node.style.setProperty("min-height", "0", "important");
        node.style.setProperty("flex", "0 0 auto", "important");
        node.style.setProperty("overflow", "visible", "important");
        node.style.removeProperty("overflow-y");
        node.style.removeProperty("overflow-x");
        node.style.removeProperty("overscroll-behavior");
      });
  }

  function apply() {
    const sourcesPanel = panel();
    if (!sourcesPanel) return false;

    const sourcesColumn = column(sourcesPanel);
    const bounds = sourcesColumn
      ? sourcesColumn.getBoundingClientRect()
      : sourcesPanel.getBoundingClientRect();

    const panelInner = sourcesPanel.querySelector("[data-testid='stVerticalBlock']");
    if (panelInner) {
      const panelHeight = Math.max(200, bounds.height);
      panelInner.style.setProperty("max-height", panelHeight + "px", "important");
      panelInner.style.setProperty("height", panelHeight + "px", "important");
      panelInner.style.setProperty("min-height", "0", "important");
      panelInner.style.setProperty("overflow", "hidden", "important");
      panelInner.style.setProperty("display", "flex", "important");
      panelInner.style.setProperty("flex-direction", "column", "important");
    }

    const header = sourcesPanel.querySelector(".st-key-sources_header");
    const headerBottom = header
      ? header.getBoundingClientRect().bottom
      : bounds.top + 200;
    const maxHeight = Math.max(160, bounds.bottom - headerBottom - 12);

    clearNestedScroll(sourcesPanel);

    scrollTargets(sourcesPanel).forEach((node) => {
      node.style.setProperty("flex", "1 1 auto", "important");
      node.style.setProperty("max-height", maxHeight + "px", "important");
      node.style.setProperty("height", maxHeight + "px", "important");
      node.style.setProperty("overflow-y", "auto", "important");
      node.style.setProperty("overflow-x", "hidden", "important");
      node.style.setProperty("min-height", "0", "important");
      node.style.setProperty("overscroll-behavior", "contain", "important");
    });

    return true;
  }

  function schedule() {
    win.requestAnimationFrame(apply);
  }

  function bind() {
    const sourcesPanel = panel();
    if (!sourcesPanel) return false;

    if (sourcesPanel.dataset.cdSourcesScrollBound === "1") {
      schedule();
      return true;
    }
    sourcesPanel.dataset.cdSourcesScrollBound = "1";

    win.addEventListener("resize", schedule);
    const observer = new win.MutationObserver(schedule);
    observer.observe(sourcesPanel, { childList: true, subtree: true });
    schedule();
    return true;
  }

  function boot() {
    if (bind()) return;
    let attempts = 0;
    const timer = win.setInterval(() => {
      attempts += 1;
      if (bind() || attempts > 80) win.clearInterval(timer);
    }, 80);
  }

  boot();
})();
</script>
        """,
        height=0,
    )
