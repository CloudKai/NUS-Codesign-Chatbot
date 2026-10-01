"""Static UI assets loaded by the Streamlit presentation layer.

Ordered stylesheet partials live in ``styles/`` and are concatenated by
``ui.theme.inject_template_css()``:

- ``00-foundations.css`` — tokens and shared baseline controls
- ``10-workspace.css`` — header, columns, resize/collapse
- ``15-nav.css`` — left chat nav and center Search pane
- ``20-studio.css`` — Thinking Path, journey, review
- ``30-chat.css`` — discussion and composer
- ``40-sources.css`` — Sources panel and source menus
- ``50-dialogs-notebooks.css`` — shared controls, dialogs, notebooks
- ``60-profile-topbar.css`` — profile settings and top-bar controls
- ``90-responsive.css`` — breakpoint overrides

Do not reorder these files without comparing the assembled CSS cascade.
"""
