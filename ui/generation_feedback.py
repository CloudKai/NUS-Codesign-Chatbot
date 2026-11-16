"""Student guidance for generation allowance and finite admission outcomes."""


def generation_limit_message(category: str) -> str | None:
    """Return safe, actionable limit copy, or None for an unrelated failure."""
    if category == "generation_budget":
        return (
            "The generation allowance is used up. It resets on the first day of next month "
            "at 00:00 UTC. You can still read notebooks, use sources and export your work. "
            "Ask your lecturer for help."
        )
    if category in {"generation_capacity", "generation_wait"}:
        return (
            "The generation waiting limit was reached. Your reply has not been generated. "
            "Retry shortly; notebooks, sources and export remain available."
        )
    if category == "generation_unavailable":
        return "Generation is temporarily unavailable. Your saved work remains available. Ask your lecturer for help."
    return None
