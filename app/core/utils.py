from datetime import datetime, timezone
from typing import Optional

class PaceCalculator:
    @staticmethod
    def estimate_longevity(pct_used: float, reset_at: Optional[datetime]) -> str:
        if pct_used <= 0: return "Stable"
        if not reset_at: return "Sustainable"
        now = datetime.now(timezone.utc)
        if reset_at.tzinfo is None: reset_at = reset_at.replace(tzinfo=timezone.utc)
        time_to_reset = (reset_at - now).total_seconds()
        if time_to_reset <= 0: return "Pending Reset"
        remaining_pct = 100 - pct_used
        if remaining_pct <= 0: return "Exhausted"
        if remaining_pct < 10: return "Fast Burn"
        if remaining_pct < 30: return "Moderate Burn"
        return "Sustainable"

def human_delta(target_dt: Optional[datetime]) -> str:
    if not target_dt: return "—"
    now = datetime.now(timezone.utc)
    if target_dt.tzinfo is None: target_dt = target_dt.replace(tzinfo=timezone.utc)
    diff = target_dt - now
    seconds = int(diff.total_seconds())
    if seconds < 0: return "Just now"
    if seconds < 60: return f"{seconds}s"
    if seconds < 3600: return f"{seconds // 60}m"
    return f"{seconds // 3600}h {(seconds % 3600) // 60}m"

def error_card(service: str, icon: str, message: str):
    return {
        "service": service,
        "icon": icon,
        "remaining": "ERR",
        "unit": "Check State",
        "reset": "—",
        "health": "critical",
        "pace": "Stopped",
        "detail": message
    }
