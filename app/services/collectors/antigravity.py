import json
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import httpx
from app.core.config import settings
from app.core.utils import PaceCalculator, human_delta
from app.services.collectors.base import BaseCollector

class AntigravityCollector(BaseCollector):
    async def collect(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        path = settings.ANTIGRAVITY_QUOTA_PATH
        try:
            with open(path, "r") as f: data = json.load(f)
            res = []
            for name, usage in data.get("models", {}).items():
                rem = usage.get("remaining_percent", 0.0)
                reset = datetime.fromtimestamp(usage["resets_at"], tz=timezone.utc) if "resets_at" in usage else None
                res.append({
                    "service": f"AG: {name}",
                    "icon": "🛸",
                    "remaining": f"{rem:.1f}%",
                    "unit": "remaining",
                    "reset": human_delta(reset),
                    "health": "good" if rem > 30 else "warning",
                    "pace": PaceCalculator.estimate_longevity(100 - rem, reset),
                    "detail": f"{name} [IDE]",
                })
            return res
        except: return []
