"""
Anthropic (Claude) quota collector — thin orchestrator.

Collection Strategy (4-tier):
1. Primary:   Statusline bridge (fast local) + OAuth API (full quota windows)
2. Secondary: Web API via Chrome sessionKey cookie
3. Tertiary:  CLI PTY (`claude /usage` parsed output)
4. Quaternary: Enhanced local log parsing (~/.claude/projects/**/*.jsonl)

Each strategy is implemented in a dedicated module and composed here via mixins:
- anthropic_oauth.py  — Token lifecycle, OAuth API client, response parsing
- anthropic_web.py    — Statusline bridge and Web API cookie strategy
- anthropic_local.py  — CLI PTY and local log parsing strategies

Token Refresh:
- Automatic refresh on 401 with Client ID auto-discovery from credentials/id_token
- Exponential backoff on transient failures; terminal failure for invalid_grant

Data Caching:
- OAuth results cached for 10 minutes to handle 429 rate limits gracefully
"""

import os
import logging
from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

import httpx

from app.core.config import settings, get_platform_config_dir
from app.services.credential_provider import credential_provider
from app.core.utils import error_card

from app.services.collectors.anthropic_oauth import AnthropicOAuthMixin
from app.services.collectors.anthropic_web import AnthropicWebMixin
from app.services.collectors.anthropic_local import AnthropicLocalMixin

logger = logging.getLogger(__name__)


class AnthropicCollector(AnthropicOAuthMixin, AnthropicWebMixin, AnthropicLocalMixin):
    """
    Collector for Anthropic (Claude) quota and usage metrics with 4-tier fallback.

    Composes all three strategy mixins. The base class chain is:
    AnthropicCollector → AnthropicOAuthMixin (→ OAuthBaseCollector → BaseCollector)
    """

    def _is_error_result(self, results: List[Dict[str, Any]]) -> bool:
        """
        Anthropic specific error check. 
        If we have ANY non-error cards (e.g. from Statusline), consider it success.
        """
        if not results:
            return True
        # Success if at least one card is NOT an error
        return all(r.get("remaining") == "ERR" for r in results)

    def __init__(self):
        """Initialize orchestrator."""
        # Credentials file path (search multiple locations)
        home = os.path.expanduser("~")
        credentials_path = os.path.join(home, ".claude", ".credentials.json")
        platform_cred_path = os.path.join(
            get_platform_config_dir("claude"), ".credentials.json"
        )
        if not os.path.exists(credentials_path) and os.path.exists(platform_cred_path):
            credentials_path = platform_cred_path

        self._name_map = {
            "five_hour": "Session Window",
            "seven_day": "Weekly Window",
            "seven_day_sonnet": "Sonnet Weekly",
            "seven_day_opus": "Opus Weekly",
            "extra_usage": "Extra Usage",
        }

        super().__init__(provider_name="Anthropic", credentials_path=credentials_path)

        # Result caching for API calls (Statusline updates independently via SmartCollector 60s TTL)
        self._cached_api_results = None
        self._last_api_fetch = None
        
        self._refresh_backoff_seconds = 30
        self._max_refresh_backoff = 21600  # 6 hours max
        self._last_statusline_data = {}    # Cache for hybrid fallback

    # ─────────────────────────── Strategy orchestration ──────────────────────

    def _fallback_strategies(self) -> List[Any]:
        """Return ordered fallback strategies: Web → CLI PTY → Local Logs."""
        return [
            self._get_claude_via_web_api,
            self._strategy_cli_pty,
            self._strategy_local_enhanced,
        ]

    async def _primary_strategy(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        """
        Hybrid primary strategy: Statusline (fast) merged with OAuth (full coverage).

        Runs both sources and deduplicates: OAuth results are added only for
        windows not already covered by the statusline.
        """
        results = []

        # 1. Statusline — fast, local, no network
        statusline_res = await self._strategy_statusline()
        results.extend(statusline_res)

        # 2. OAuth API — full window data
        token = await self._get_valid_token(client)
        if token:
            # Mixin handles its own proactive 429 backoff and internal 10m cache
            oauth_res = await self._get_claude_oauth_with_cache(client, token)

            # Reactive 401 handling: refresh and retry once
            is_401 = any(
                "Expired/Invalid Token" in str(r.get("detail", "")) for r in oauth_res
            )
            if is_401 and not self._terminal_failure:
                async with self._refresh_lock:
                    new_creds = await self._execute_refresh(client)
                    if new_creds:
                        new_token = new_creds.get("claudeAiOauth", {}).get("accessToken")
                        self._persist_credentials(new_creds)
                        oauth_res = await self._get_claude_oauth(client, new_token)

            # Merge OAuth
            statusline_keys = {r["service"] for r in results}
            is_oauth_error = any(r.get("remaining") == "ERR" for r in oauth_res)
            
            # Add successful OAuth cards
            for r in oauth_res:
                if r["service"] not in statusline_keys and r.get("remaining") != "ERR":
                    results.append(r)

        # 3. Web API fallback (Chrome/Safari cookies) — try if results are still missing or OAuth failed
        # We only do this if OAuth didn't give us good data, to avoid hitting the web API too much
        has_full_coverage = any("Weekly" in r["service"] for r in results)
        if not has_full_coverage:
            web_res = await self._get_claude_via_web_api(client)
            if web_res:
                current_keys = {r["service"] for r in results}
                for r in web_res:
                    if r["service"] not in current_keys:
                        results.append(r)

        # 4. Final Cleanup: If we have ANY successful cards, remove any leftover error cards
        # to prevent triggering SmartCollector's failure fallback.
        has_success = any(r.get("remaining") != "ERR" for r in results)
        if has_success:
            results = [r for r in results if r.get("remaining") != "ERR"]

        # logger.info(f"Claude primary strategy final cards: {[r['service'] for r in results]}")
        return results

    async def _error_handler(self) -> List[Dict[str, Any]]:
        """Return a descriptive error card when all strategies fail."""
        # Check for proactive rate limit backoff
        backoff_until = getattr(self, "_last_429_backoff_until", None)
        if backoff_until and datetime.now(timezone.utc) < backoff_until:
            wait_rem = (backoff_until - datetime.now(timezone.utc)).total_seconds()
            return [error_card(
                "Claude Pro", "🟠", f"Rate Limited (429) - Retry in {wait_rem/60:.0f}m",
                error_type="rate_limited",
            )]

        if credential_provider.get_claude_token():
            return [error_card(
                "Claude Pro", "🟠", "No data — OAuth failed & Logs empty",
                error_type="missing_config",
            )]

        if await self._has_web_cookie():
            return [error_card(
                "Claude Pro", "🟠", "No data — Web API failed & Logs empty",
                error_type="missing_config",
            )]

        return [error_card(
            "Claude Pro", "🟠",
            "No data — Set CLAUDE_CODE_OAUTH_TOKEN or login to claude.ai",
            error_type="missing_config",
        )]
