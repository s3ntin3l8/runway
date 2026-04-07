"""
OpenCode quota collector with dual data sources.

Collection Strategy:
1. OpenCode Go API
   - Requires OPENCODE_GO_API_KEY environment variable
   - Calls https://api.opencode.ai/v1/user/usage with Bearer auth
   - Returns USD-based spending: total_usage_usd and hard_limit_usd
   - Rolling 5-hour window for rate limiting
   
2. OpenCode TUI Local Database
   - Reads SQLite database at OPENCODE_DB_PATH (local development)
   - Queries session table to sum lines changed (additions + deletions)
   - Historical data (no reset window)
   - Used as complementary data source showing local activity

Error Handling:
- Missing API key: Silently skips API collector
- API HTTP errors: Returns error card with status code
- No limit set: Returns error card (API misconfiguration)
- DB errors: Returns error card with first 15 chars of error

Data Representation:
- OpenCode Go: USD spending model with hard limit
- OpenCode TUI: Lines of code changed (development metrics)
"""

import os
from typing import List, Dict, Any
import httpx
from app.core.config import settings
from app.core.utils import error_card
from app.services.collectors.base import BaseCollector

class OpenCodeCollector(BaseCollector):
    async def collect(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        """
        Collect OpenCode quota from both API and local database.
        
        Returns cards for:
        - OpenCode Go API (USD spending)
        - OpenCode TUI database (lines changed)
        
        Returns:
            List[Dict[str, Any]]: Cards for available data sources
        """
        results = []
        
        # 1. OpenCode Go (API)
        go_res = await self._get_opencode_go(client)
        if go_res: results.extend(go_res)
        
        # 2. OpenCode TUI (Local DB)
        tui_res = await self._get_opencode_tui()
        if tui_res: results.extend(tui_res)
        
        return results

    async def _get_opencode_go(self, client: httpx.AsyncClient):
        """
        Fetch OpenCode Go API quota (USD-based spending).
        
        Requires OPENCODE_GO_API_KEY. Returns error card if key missing or API fails.
        
        Note: The OpenCode Go API endpoint (api.opencode.ai) appears to be deprecated
        as of April 2026. The endpoint returns "Not Found" for all usage queries.
        Users should check usage at https://opencode.ai/auth instead.
        
        Returns:
            List[Dict[str, Any]]: Single card with remaining budget or error
        """
        key = settings.OPENCODE_GO_API_KEY
        if not key: return []
        try:
            resp = await client.get("https://api.opencode.ai/v1/user/usage", headers={"Authorization": f"Bearer {key}"})
            if resp.status_code != 200: 
                return [error_card("OpenCode Go", "🚀", f"HTTP {resp.status_code}")]
            
            # Check if response is valid JSON
            content_type = resp.headers.get("content-type", "")
            if "application/json" not in content_type:
                # API endpoint deprecated - return informative message
                return [{
                    "service": "OpenCode Go",
                    "icon": "🚀",
                    "remaining": "N/A",
                    "unit": "—",
                    "reset": "Check Console",
                    "health": "warning",
                    "pace": "API Unavailable",
                    "detail": "Visit opencode.ai/auth for usage",
                }]
            
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
            # Handle JSON parse errors (API returning HTML instead of JSON)
            error_msg = str(e)
            if "Expecting value" in error_msg or "not accessible" in error_msg.lower():
                return [{
                    "service": "OpenCode Go",
                    "icon": "🚀",
                    "remaining": "N/A",
                    "unit": "—",
                    "reset": "Check Console",
                    "health": "warning",
                    "pace": "API Unavailable",
                    "detail": "Visit opencode.ai/auth for usage",
                }]
            return [error_card("OpenCode Go", "🚀", f"Fail: {error_msg[:15]}")]

    async def _get_opencode_tui(self):
        """
        Fetch OpenCode TUI local database statistics.
        
        Reads SQLite database and sums tokens and cost from recent messages.
        Returns empty list if database not found (TUI not in use).
        
        Returns:
            List[Dict[str, Any]]: Single card with token usage or error
        """
        db = settings.OPENCODE_DB_PATH
        if not os.path.exists(db): return []
        try:
            import aiosqlite
            from datetime import datetime, timezone, timedelta
            
            cutoff_ms = int((datetime.now(timezone.utc) - timedelta(hours=24)).timestamp() * 1000)
            
            async with aiosqlite.connect(db) as conn:
                async with conn.execute("""
                    SELECT 
                        SUM(json_extract(data, '$.tokens.input')),
                        SUM(json_extract(data, '$.tokens.output')),
                        SUM(json_extract(data, '$.cost')),
                        COUNT(*)
                    FROM message
                    WHERE time_created > ?
                      AND json_valid(data)
                      AND json_extract(data, '$.role') = 'assistant'
                """, (cutoff_ms,)) as cursor:
                    row = await cursor.fetchone()
                    
            inp = int(row[0] or 0)
            out = int(row[1] or 0)
            cost = float(row[2] or 0.0)
            count = int(row[3] or 0)
            total = inp + out
            
            return [{
                "service": "OpenCode TUI",
                "icon": "⚡",
                "remaining": f"{total:,}",
                "unit": "tokens (24h)",
                "reset": "Rolling 24h",
                "health": "good",
                "pace": "Stable",
                "detail": f"{count} msgs · ${cost:.4f} · {inp:,} in / {out:,} out",
            }]
        except Exception as e: 
            return [error_card("OpenCode TUI", "⚡", f"DB Error: {str(e)[:15]}")]
