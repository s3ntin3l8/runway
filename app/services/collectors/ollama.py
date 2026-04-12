"""
Ollama Cloud quota collector.

Collection Strategy:
1. Primary: Scrape https://ollama.com/settings
   - Requires session cookie from environment (OLLAMA_SESSION_TOKEN) or browser.
   - Parses Cloud Usage section for session and weekly quotas.
   - Extracts plan name, account email, usage percentages, and reset timestamps.
"""

import re
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional
import httpx
from app.services.collectors.base import BaseCollector
from app.core.browser_cookies import get_cookie_from_registry
from app.core.utils import PaceCalculator, human_delta, error_card, http_request_with_retry

logger = logging.getLogger(__name__)


class OllamaCollector(BaseCollector):
    def __init__(self):
        self.target_url = "https://ollama.com/settings"
        self.labels = ["Session usage", "Hourly usage", "Weekly usage"]

    async def _primary_strategy(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        """Scrape Ollama settings page."""
        cookie_val = get_cookie_from_registry("ollama")
        if not cookie_val:
            return []

        headers = {
            "Cookie": f"session={cookie_val}",  # Default to 'session', but many names work
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/133.0.0.0 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Referer": "https://ollama.com",
        }

        # Try multiple cookie names if the first one doesn't work? 
        # Actually the registry maps all possible names to 'cookie_session'.
        # We'll try a few common ones in the header just in case.
        headers["Cookie"] = f"session={cookie_val}; ollama_session={cookie_val}; __Host-ollama_session={cookie_val}; __Secure-next-auth.session-token={cookie_val}"

        try:
            resp = await http_request_with_retry(client, "GET", self.target_url, headers=headers, timeout=15)
            if resp.status_code == 200:
                return self._parse_html(resp.text)
            elif resp.status_code in (401, 403):
                logger.debug("Ollama auth failed (401/403)")
            else:
                logger.debug(f"Ollama fetch failed with status {resp.status_code}")
        except Exception as e:
            logger.debug(f"Ollama fetch error: {e}")

        return []

    def _parse_html(self, html: str) -> List[Dict[str, Any]]:
        """Parse the settings page HTML for usage data."""
        cards = []
        now = datetime.now(timezone.utc)

        # 1. Extract Plan Name
        plan_name = None
        plan_match = re.search(r'Cloud Usage\s*</span>\s*<span[^>]*>([^<]+)</span>', html, re.DOTALL)
        if plan_match:
            plan_name = plan_match.group(1).strip()

        # 2. Extract Account Email
        email = None
        email_match = re.search(r'id="header-email"[^>]*>([^<]+)<', html)
        if email_match:
            email = email_match.group(1).strip()

        # 3. Parse Usage Blocks
        # The Swift code finds the label, then takes 800 chars after it.
        session_block = self._get_usage_block(["Session usage", "Hourly usage"], html)
        weekly_block = self._get_usage_block(["Weekly usage"], html)

        if session_block:
            cards.append(self._make_card("Ollama Session", session_block, plan_name, email, now))
        
        if weekly_block:
            cards.append(self._make_card("Ollama Weekly", weekly_block, plan_name, email, now))

        return cards

    def _get_usage_block(self, labels: List[str], html: str) -> Optional[Dict[str, Any]]:
        for label in labels:
            idx = html.find(label)
            if idx == -1:
                continue
            
            # Take a window of 800 chars after the label
            window = html[idx : idx + 800]
            
            # Parse percentage
            pct = None
            # Pattern 1: "XX% used"
            pct_match = re.search(r'([0-9]+(?:\.[0-9]+)?)\s*%\s*used', window, re.IGNORECASE)
            if pct_match:
                pct = float(pct_match.group(1))
            else:
                # Pattern 2: "width: XX%"
                pct_match = re.search(r'width:\s*([0-9]+(?:\.[0-9]+)?)%', window, re.IGNORECASE)
                if pct_match:
                    pct = float(pct_match.group(1))
            
            if pct is None:
                continue

            # Parse reset date
            resets_at = None
            date_match = re.search(r'data-time="([^"]+)"', window)
            if date_match:
                raw_date = date_match.group(1)
                try:
                    # ISO 8601 parsing
                    resets_at = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
                except ValueError:
                    pass
            
            return {"used_percent": pct, "resets_at": resets_at}
        return None

    def _make_card(self, service_name: str, block: Dict[str, Any], plan: Optional[str], email: Optional[str], now: datetime) -> Dict[str, Any]:
        pct = block["used_percent"]
        resets_at = block["resets_at"]
        
        detail = f"{pct:.1f}% used"
        if plan:
            detail = f"{plan} · {detail}"
        if email:
            detail = f"{detail} · {email}"

        return {
            "service": service_name,
            "icon": "🦙",
            "remaining": f"{(100-pct):.1f}%",
            "unit": "remaining",
            "reset": human_delta(resets_at),
            "health": "good" if pct < 80 else "warning" if pct < 95 else "danger",
            "pace": PaceCalculator.estimate_longevity(pct, resets_at),
            "detail": detail,
            "used_value": float(pct),
            "limit_value": 100.0,
            "unit_type": "percent",
            "reset_at": resets_at.isoformat() if resets_at else None,
            "data_source": "web_scrape",
            "tier": plan.lower() if plan else "unknown",
            "usage_url": self.target_url,
            "updated_at": now.isoformat(),
        }

    def _fallback_strategies(self) -> List[Any]:
        return []

    async def _error_handler(self) -> List[Dict[str, Any]]:
        return [
            error_card(
                "Ollama Cloud", "🦙", "Not logged in or parsing failed", error_type="missing_config"
            )
        ]
