"""Edit-bubble sizing tokens shared with the chat stylesheet.

``USER_BUBBLE_MAX_ROWS`` is the single source of truth for the bubble and edit
cap. Keep ``ui/assets/styles/00-foundations.css`` ``--cd-user-bubble-max-rows``
in sync.

The inline editor grows with CSS ``field-sizing: content`` (same approach as the
composer), capped at ``USER_BUBBLE_MAX_ROWS``. No per-keystroke layout JS.
"""

from __future__ import annotations

# Keep in sync with --cd-user-bubble-max-rows / row-height tokens in styles/00-foundations.css.
USER_BUBBLE_MAX_ROWS = 8
USER_BUBBLE_FONT_REM = 0.9
USER_BUBBLE_LINE_HEIGHT = 1.45
# Streamlit ``st.text_area`` initial height (px); CSS field-sizing grows up to max.
USER_MESSAGE_EDIT_HEIGHT_PX = round(
    USER_BUBBLE_FONT_REM * 16 * USER_BUBBLE_LINE_HEIGHT * 2
)


def sync_user_message_edit_layout() -> None:
    """No-op kept as a stable call site for the edit bubble.

    Sizing is CSS ``field-sizing: content`` plus ``USER_MESSAGE_EDIT_HEIGHT_PX``.
    """
    return
