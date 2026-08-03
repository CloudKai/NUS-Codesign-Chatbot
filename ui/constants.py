"""Shared Streamlit UI constants."""

RESPONSE_LANGUAGES = ("English", "中文", "Bahasa Melayu", "தமிழ்")
APPEARANCE_MODES = ("System", "Light", "Dark")

ACTIONABLE_REVIEW_FEEDBACK: dict[str, tuple[str, tuple[str, str]]] = {
    "focus": (
        "You have identified a meaningful topic and are asking a question that can be refined.",
        (
            "Name the specific group, setting, or context you want to study.",
            "Choose one outcome that would show meaningful change.",
        ),
    ),
    "evidence": (
        "You are bringing evidence into the discussion instead of relying on a claim alone.",
        (
            "Compare the quality and relevance of your strongest sources.",
            "Name one limitation that could weaken the evidence.",
        ),
    ),
    "assumptions": (
        "You are beginning to make the reasoning behind your claim visible.",
        (
            "State the assumption connecting your evidence to your claim.",
            "Test what changes if that assumption is false.",
        ),
    ),
    "perspectives": (
        "You are considering more than one plausible interpretation.",
        (
            "Represent the strongest competing explanation fairly.",
            "Explain what evidence would distinguish between the views.",
        ),
    ),
    "synthesis": (
        "You are weighing evidence and alternatives rather than listing them separately.",
        (
            "Explain which consideration deserves the most weight and why.",
            "Qualify your claim where the evidence remains uncertain.",
        ),
    ),
    "conclusion": (
        "You are forming a conclusion that reflects the reasoning developed in this notebook.",
        (
            "State your confidence and the most important limitation.",
            "Identify the next justified question or action.",
        ),
    ),
}
