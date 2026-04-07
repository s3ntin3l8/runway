import os
from datetime import datetime, timezone
from typing import List, Dict, Any
import httpx
from app.core.config import settings
from app.core.utils import human_delta, error_card
from app.services.collectors.base import BaseCollector

class GitHubCollector(BaseCollector):
    async def collect(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        token = settings.GITHUB_TOKEN
        if not token: return []
        try:
            # Use Copilot internal endpoints for detailed metrics
            headers = {
                "Authorization": f"token {token}",
                "X-GitHub-Api-Version": "2025-04-01",
                "Accept": "application/json"
            }
            
            # 1. Fetch Copilot Token Info (includes usage for free/limited users)
            token_resp = await client.get("https://api.github.com/copilot_internal/v2/token", headers=headers)
            
            # 2. Fetch User/Quota Info (includes usage snapshots for Pro/Enterprise users)
            user_resp = await client.get("https://api.github.com/copilot_internal/user", headers=headers)
            
            cards = []
            
            if token_resp.status_code == 200:
                token_data = token_resp.json()
                if "limited_user_quotas" in token_data:
                    quotas = token_data["limited_user_quotas"]
                    reset_date = token_data.get("limited_user_reset_date")
                    reset_at = None
                    if reset_date:
                        try: reset_at = datetime.fromisoformat(reset_date.replace("Z", "+00:00"))
                        except: pass
                    
                    for key in ["completions", "chat"]:
                        if key in quotas:
                            val = quotas[key]
                            cards.append({
                                "service": f"Copilot ({key.title()})",
                                "icon": "🐙",
                                "remaining": f"{val:,}",
                                "unit": "remaining",
                                "reset": human_delta(reset_at),
                                "health": "good" if val > 10 else "warning",
                                "pace": "Manual",
                                "detail": f"{val} requests left [Internal]",
                            })

            if user_resp.status_code == 200:
                user_data = user_resp.json()
                snapshots = user_data.get("quota_snapshots", [])
                plan = user_data.get("copilot_plan", "Individual")
                
                for snap in snapshots:
                    metric_raw = snap.get("metric", "unknown")
                    metric = metric_raw.replace("_", " ").title()
                    rem = snap.get("remaining")
                    ent = snap.get("entitlement")
                    
                    if rem is not None and ent is not None:
                        pct = (ent - rem) / ent * 100 if ent > 0 else 0
                        cards.append({
                            "service": f"Copilot ({metric})",
                            "icon": "🐙",
                            "remaining": f"{rem:,}",
                            "unit": f"/ {ent:,}",
                            "reset": "Rolling",
                            "health": "good" if (rem/ent) > 0.3 else "warning" if (rem/ent) > 0.1 else "critical",
                            "pace": "Sustainable",
                            "detail": f"{pct:.1f}% used • {plan} [Snapshot]",
                        })
            
            # Fallback to standard rate limit if no specific copilot data found
            if not cards:
                resp = await client.get("https://api.github.com/rate_limit", headers={"Authorization": f"Bearer {token}"})
                if resp.status_code == 200:
                    data = resp.json()["resources"]["core"]
                    rem, lim = data["remaining"], data["limit"]
                    reset_at = datetime.fromtimestamp(data["reset"], tz=timezone.utc)
                    cards.append({
                        "service": "GitHub API",
                        "icon": "🐙",
                        "remaining": f"{rem:,}",
                        "unit": "requests",
                        "reset": human_delta(reset_at),
                        "health": "good" if rem/lim > 0.3 else "warning",
                        "pace": "Stable",
                        "detail": f"{rem}/{lim} [API fallback]",
                    })
            
            return cards
        except Exception as e:
            return [error_card("GitHub Copilot", "🐙", f"Fail: {str(e)[:15]}")]
