import os
import glob
import json
from datetime import datetime, timedelta, timezone
from typing import List, Dict, Any, Optional
import httpx
from app.core.config import settings
from app.core.utils import PaceCalculator, human_delta, error_card
from app.services.collectors.base import BaseCollector

class AnthropicCollector(BaseCollector):
    async def collect(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        results = []
        if settings.CLAUDE_CODE_OAUTH_TOKEN:
            oauth_res = await self._get_claude_oauth(client, settings.CLAUDE_CODE_OAUTH_TOKEN)
            results.extend(oauth_res)
        else:
            local_res = await self._get_claude_local()
            if local_res:
                results.extend(local_res)
        return results

    async def _get_claude_oauth(self, client: httpx.AsyncClient, token: str):
        url = "https://api.anthropic.com/api/oauth/usage"
        headers = {"Authorization": f"Bearer {token}", "anthropic-beta": "oauth-2025-04-20"}
        try:
            resp = await client.get(url, headers=headers, timeout=10.0)
            if resp.status_code == 401: return [error_card("Claude Pro", "🟠", "Unauthorized (OAuth)")]
            if resp.status_code != 200: return [error_card("Claude Pro", "🟠", f"API Error {resp.status_code}")]
            
            data = resp.json()
            results = []
            for key, usage in data.items():
                if not isinstance(usage, dict) or "utilization" not in usage:
                    continue
                
                u_type = key.replace("_", " ").title()
                pct_used = usage.get("utilization", 0.0)
                remaining_pct = 100.0 - pct_used
                
                reset_raw = usage.get("resets_at") or usage.get("resetsAt")
                reset_at = None
                if reset_raw:
                    try:
                        reset_at = datetime.fromisoformat(reset_raw.replace("Z", "+00:00"))
                    except:
                        pass
                
                results.append({
                    "service": f"Claude ({u_type})",
                    "icon": "🟠",
                    "remaining": f"{remaining_pct:.1f}%",
                    "unit": "capacity",
                    "reset": human_delta(reset_at),
                    "health": "good" if pct_used < 70 else "warning" if pct_used < 90 else "critical",
                    "pace": PaceCalculator.estimate_longevity(pct_used, reset_at),
                    "detail": f"{pct_used:.1f}% of quota used [OAuth]",
                })
            return results if results else [error_card("Claude Pro", "🟠", "No quota data")]
        except Exception as e: 
            return [error_card("Claude Pro", "🟠", f"Connection Fail: {str(e)[:20]}")]

    async def _get_claude_local(self):
        projects_dir = settings.CLAUDE_PROJECTS_DIR
        limit = 2000000
        try:
            files = glob.glob(f"{projects_dir}/**/*.jsonl", recursive=True)
            if not files: return None
            cutoff = datetime.now(timezone.utc) - timedelta(hours=5)
            total_tokens = 0
            oldest: Optional[datetime] = None
            for fpath in files:
                with open(fpath, "r", encoding="utf-8") as f:
                    for line in f:
                        entry = json.loads(line)
                        if entry.get("type") != "assistant": continue
                        ts = datetime.fromisoformat(entry["timestamp"].replace("Z", "+00:00"))
                        if ts < cutoff: continue
                        usage = entry.get("message", {}).get("usage", {})
                        total_tokens += (usage.get("input_tokens", 0) + usage.get("output_tokens", 0))
                        if not oldest or ts < oldest: oldest = ts
            remaining = max(0, limit - total_tokens)
            pct = (total_tokens / limit * 100) if limit > 0 else 0
            reset_at = (oldest + timedelta(hours=5)) if oldest else None
            return [{
                "service": "Claude Pro",
                "icon": "🟠",
                "remaining": f"{remaining:,}",
                "unit": "tokens / 5h",
                "reset": human_delta(reset_at),
                "health": "good" if pct < 70 else "warning" if pct < 90 else "critical",
                "pace": PaceCalculator.estimate_longevity(pct, reset_at),
                "detail": f"{total_tokens:,} / {limit:,} [Logs]",
            }]
        except: return None
