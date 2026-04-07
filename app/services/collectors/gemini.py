import glob
import json
from typing import List, Dict, Any
import httpx
from app.core.config import settings
from app.services.collectors.base import BaseCollector

class GeminiCollector(BaseCollector):
    async def collect(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        sessions_dir = settings.GEMINI_SESSIONS_DIR
        try:
            files = glob.glob(f"{sessions_dir}/*.jsonl")
            if not files: return []
            total = 0
            for fpath in files:
                with open(fpath, "r") as f:
                    for line in f:
                        u = json.loads(line).get("usage", {})
                        total += (u.get("prompt_tokens", 0) + u.get("completion_tokens", 0))
            return [{
                "service": "Gemini CLI",
                "icon": "🔵",
                "remaining": f"{total:,}",
                "unit": "tokens (24h)",
                "reset": "Rolling 24h",
                "health": "good",
                "pace": "Stable",
                "detail": "Local session logs",
            }]
        except: return []
