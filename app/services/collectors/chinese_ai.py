from typing import List, Dict, Any
import httpx
from app.core.config import settings
from app.core.utils import error_card
from app.services.collectors.base import BaseCollector

class ChineseAICollector(BaseCollector):
    async def collect(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        results = []
        
        # 1. zAI (GLM)
        zai_res = await self._get_zai(client)
        if zai_res: results.extend(zai_res)
        
        # 2. Kimi
        kimi_res = await self._get_kimi(client)
        if kimi_res: results.extend(kimi_res)
        
        return results

    async def _get_zai(self, client: httpx.AsyncClient):
        key = settings.ZAI_API_KEY
        if not key or "zai" in key: return [error_card("zAI", "🌐", "Missing/Invalid Key")]
        try:
            resp = await client.get("https://open.bigmodel.cn/api/paas/v4/users/me/balance", headers={"Authorization": f"Bearer {key}"})
            if resp.status_code != 200: return [error_card("zAI", "🌐", "API Error")]
            bal = float(resp.json().get("data", {}).get("available_balance", 0))
            return [{
                "service": "zAI (GLM)",
                "icon": "🌐",
                "remaining": f"¥{bal:.2f}",
                "unit": "balance",
                "reset": "Manual",
                "health": "good" if bal > 10 else "warning",
                "pace": "Stable",
                "detail": "Prepaid balance",
            }]
        except: return [error_card("zAI", "🌐", "Connection Failed")]

    async def _get_kimi(self, client: httpx.AsyncClient):
        key = settings.KIMI_API_KEY
        if not key or len(key) < 10: return [error_card("Kimi K2.5", "🌙", "Missing/Invalid Key")]
        try:
            resp = await client.get("https://api.moonshot.cn/v1/users/me/balance", headers={"Authorization": f"Bearer {key}"})
            if resp.status_code == 401: return [error_card("Kimi K2.5", "🌙", "Unauthorized")]
            if resp.status_code != 200: return [error_card("Kimi K2.5", "🌙", f"HTTP {resp.status_code}")]
            bal = float(resp.json().get("data", {}).get("available_balance", 0))
            return [{
                "service": "Kimi K2.5",
                "icon": "🌙",
                "remaining": f"${bal:.2f}",
                "unit": "balance",
                "reset": "Manual",
                "health": "good" if bal > 5 else "warning",
                "pace": "Stable",
                "detail": "Prepaid balance",
            }]
        except: return [error_card("Kimi K2.5", "🌙", "Connection Failed")]
