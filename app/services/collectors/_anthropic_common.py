"""Shared constants and helpers used across all Anthropic collector mixins."""

ANTHROPIC_WINDOW_NAME_MAP: dict[str, str] = {
    "five_hour": "Session Window",
    "seven_day": "Weekly Window",
    "seven_day_sonnet": "Sonnet Weekly",
    "seven_day_opus": "Opus Weekly",
    "seven_day_omelette": "Claude Design",
    "extra_usage": "Extra Usage",
}


def classify_anthropic_window_type(key: str) -> str:
    """Map an Anthropic usage window key to its canonical window_type string."""
    if key == "five_hour":
        return "session"
    if key in ("seven_day_sonnet", "seven_day_opus", "seven_day_omelette"):
        return key  # preserved as-is for per-model classification
    if "seven_day" in key:
        return "weekly"
    return "unknown"
