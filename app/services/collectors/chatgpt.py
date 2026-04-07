import os
import glob
import json
from datetime import datetime, timezone
from typing import List, Dict, Any
import httpx
from app.core.config import settings
from app.core.utils import PaceCalculator, human_delta, error_card
from app.services.collectors.base import BaseCollector

class ChatGPTCollector(BaseCollector):
    async def collect(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        path = settings.CHATGPT_SESSIONS_DIR
        try:
            files = glob.glob(f"{path}/**/*.jsonl", recursive=True)
            if not files: return [error_card("ChatGPT Codex", "💬", "No logs")]
            latest = max(files, key=os.path.getmtime)
            with open(latest, "r") as f:
                lines = f.readlines()
                if not lines: return [error_card("ChatGPT Codex", "💬", "Empty log")]
                usage = json.loads(lines[-1])
            pct = usage.get("used_percent", 0.0)
            reset_at = datetime.fromtimestamp(usage["resets_at"], tz=timezone.utc) if "resets_at" in usage else None
            return [{
                "service": "ChatGPT Codex",
                "icon": "💬",
                "remaining": f"{(100-pct):.1f}%",
                "unit": "remaining",
                "reset": human_delta(reset_at),
                "health": "good" if pct < 80 else "warning",
                "pace": PaceCalculator.estimate_longevity(pct, reset_at),
                "detail": f"{pct:.1f}% used [Cache]",
            }]
        except: return [error_card("ChatGPT Codex", "💬", "Parse Error")]
