"""Shared Streamlit UI constants.

These values are presentation-facing only. Stage review copy is derived in
``backend.student_journey.learning_review`` from coach assessments and the
latest Deep Review snapshot when available.
"""

PRODUCT_TITLE = "CDE2300 Design Thinking Companion"
PRODUCT_SUBTITLE = "Product Design and Innovation"

# Languages accepted in persisted notebook metadata. The profile menu no
# longer exposes a language picker.
RESPONSE_LANGUAGES = ("English", "中文", "Bahasa Melayu", "தமிழ்")

# Appearance modes for theme CSS; ``System`` follows the device preference.
APPEARANCE_MODES = ("System", "Light", "Dark")
DEFAULT_APPEARANCE = "System"
