import os
from typing import List, Dict, Any
import httpx
from app.core.config import settings
from app.core.utils import error_card
from app.services.collectors.base import BaseCollector

class OpenCodeCollector(BaseCollector):
    async def collect(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        results = []
        
        # 1. OpenCode Go (API)
        go_res = await self._get_opencode_go(client)
        if go_res: results.extend(go_res)
        
        # 2. OpenCode TUI (Local DB)
        tui_res = await self._get_opencode_tui()
        if tui_res: results.extend(tui_res)
        
        return results

    async def _get_opencode_go(self, client: httpx.AsyncClient):
        key = settings.OPENCODE_GO_API_KEY
        if not key: return []
        try:
            resp = await client.get("https://api.opencode.ai/v1/user/usage", headers={"Authorization": f"Bearer {key}"})
            if resp.status_code != 200: 
                return [error_card("OpenCode Go", "🚀", f"HTTP {resp.status_code}")]
            
            data = resp.json()
            used, lim = data.get("total_usage_usd", 0), data.get("hard_limit_usd", 0)
            if lim == 0: return [error_card("OpenCode Go", "🚀", "No limit set")]
            rem = max(0, lim - used)
            pct = (used / lim * 100)
            return [{
                "service": "OpenCode Go",
                "icon": "🚀",
                "remaining": f"${rem:.2f}",
                "unit": "USD",
                "reset": "Rolling 5h",
                "health": "good" if pct < 70 else "warning",
                "pace": "Stable",
                "detail": f"${used:.2f}/${lim:.2f} ({pct:.1f}%) [API]",
            }]
        except Exception as e: 
            return [error_card("OpenCode Go", "🚀", f"Fail: {str(e)[:15]}")]

    async def _get_opencode_tui(self):
        db = settings.OPENCODE_DB_PATH
        if not os.path.exists(db): return []
        try:
            import aiosqlite
            async with aiosqlite.connect(db) as conn:
                async with conn.execute("SELECT SUM(summary_additions + summary_deletions) FROM session") as cursor:
                    row = await cursor.fetchone()
                    tokens = row[0] or 0
            return [{
                "service": "OpenCode TUI",
                "icon": "⚡",
                "remaining": f"{tokens:,}",
                "unit": "lines changed",
                "reset": "History",
                "health": "good",
                "pace": "Stable",
                "detail": "Local DB",
            }]
        except Exception as e: 
            return [error_card("OpenCode TUI", "⚡", f"DB Error: {str(e)[:15]}")]
