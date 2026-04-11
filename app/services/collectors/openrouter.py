import logging
import httpx
from typing import List, Dict, Any, Optional
from app.services.collectors.base import BaseCollector
from app.core.config import settings
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

class OpenRouterCollector(BaseCollector):
    """
    Collector for OpenRouter usage and credits.
    Uses: https://openrouter.ai/api/v1/credits
    """

    def __init__(self):
        super().__init__(provider_name="OpenRouter")
        self.api_key = settings.OPENROUTER_API_KEY

    async def collect(self) -> List[Dict[str, Any]]:
        """Collect usage data from OpenRouter."""
        if not self.api_key:
            return []

        async with httpx.AsyncClient() as client:
            try:
                headers = {
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }
                
                # Check credits/usage
                resp = await client.get(
                    "https://openrouter.ai/api/v1/credits",
                    headers=headers,
                    timeout=10
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    if "data" in data:
                        info = data["data"]
                        total_credits = info.get("total_credits", 0.0)
                        usage = info.get("usage", 0.0)
                        remaining = max(0, total_credits - usage)
                        
                        return [{
                            "service": "OpenRouter Credits",
                            "icon": "🚀",
                            "remaining": f"${remaining:.2f}",
                            "unit": "USD",
                            "reset": "Prepaid",
                            "health": "good" if remaining > 5.0 else "warning" if remaining > 1.0 else "critical",
                            "pace": "Stable",
                            "detail": f"Used: ${usage:.2f} of ${total_credits:.2f} [API]",
                            "used_value": usage,
                            "limit_value": total_credits,
                            "unit_type": "currency",
                            "data_source": "api",
                            "updated_at": datetime.now(timezone.utc).isoformat(),
                        }]
                else:
                    logger.error(f"OpenRouter API error (HTTP {resp.status_code}): {resp.text}")
                    
            except Exception as e:
                logger.error(f"Failed to collect OpenRouter usage: {e}")

        return []
