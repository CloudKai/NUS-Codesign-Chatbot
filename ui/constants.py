"""Shared Streamlit UI constants.

These values are presentation-facing only. Stage review copy is derived in
``backend.student_journey.learning_review`` from coach assessments and the
latest Deep Review snapshot when available.
"""

from module_profile import load_module_profile


def product_profile():
    """Return the validated deployment profile for presentation copy."""
    return load_module_profile()


# Compatibility constants retain the local-demo values for code/tests that
# import them directly. New presentation code should use ``product_profile``.
PRODUCT_TITLE = product_profile().product_title
PRODUCT_SUBTITLE = product_profile().module_name

# Languages accepted in persisted notebook metadata. The profile menu no
# longer exposes a language picker.
RESPONSE_LANGUAGES = ("English", "中文", "Bahasa Melayu", "தமிழ்")

# Appearance modes for theme CSS; ``System`` follows the device preference.
APPEARANCE_MODES = ("System", "Light", "Dark")
DEFAULT_APPEARANCE = "System"
