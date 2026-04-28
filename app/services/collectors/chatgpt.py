"""
ChatGPT Codex quota collector orchestrating API and log fallback strategies.
"""

import logging
import uuid
from typing import Any

import httpx

from app.core.utils import error_card
from app.services.collectors.base import BaseCollector
from app.services.collectors.chatgpt_local import ChatGPTLocalMixin

# Mixins
from app.services.collectors.chatgpt_oauth import ChatGPTWebOAuthMixin
from app.services.collectors.chatgpt_web import ChatGPTWebMixin

logger = logging.getLogger(__name__)


class ChatGPTCollector(
    ChatGPTWebOAuthMixin,
    ChatGPTWebMixin,
    ChatGPTLocalMixin,
    BaseCollector,
):
    """
    Orchestrator for ChatGPT data collection.
    Inherits from mixins for auth, API, and local strategies.
    """

    PROVIDER_ID = "chatgpt"
    DEFAULT_WINDOW_TYPE = "weekly"

    STRATEGIES: dict[str, tuple[str, str] | tuple[str, str, dict]] = {
        "web": ("Web Gateway (web)", "_strategy_web_wrap"),
        "cli": ("CLI RPC (local)", "_collect_via_cli_rpc"),
        "local": ("Local Enrichment (local)", "_strategy_local_enrichment", {"enrich": True}),
    }

    def __init__(self, account_id: str | None = None, account_label: str | None = None):
        """Initialize orchestrator."""
        super().__init__(account_id=account_id, account_label=account_label)

        # In-memory session state for mixins
        self._refreshed_token = None
        self._refreshed_token_expiry = None
        self._device_id = str(uuid.uuid4())

    async def is_configured(self) -> bool:
        """Check if ChatGPT auth data (logs or tokens) is present."""
        # Use None for client to avoid triggering background refreshes during config check
        auth = await self._get_auth_data(None)

        # Check if we have an OAuth token, a session cookie, or local logs
        has_auth = bool(auth.get("token"))
        has_local = auth.get("source") == "local"

        return has_auth or has_local

    def _fallback_strategies(self) -> list[Any]:
        """Return the fallback strategies for ChatGPT."""
        return [
            self._collect_via_cli_rpc,
        ]

    async def _primary_strategy(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """Web API / OAuth strategy."""
        auth = await self._get_auth_data(client)
        token = auth.get("token")
        account_id = auth.get("account_id")

        if not token:
            return []

        try:
            return await self._fetch_api_data(
                client,
                token,
                account_id,
                auth.get("source", "oauth"),
                input_source=auth.get("input_source", "server"),
            )
        except Exception as e:
            logger.debug(f"ChatGPT Web API failed: {e}")
        return []

    async def _strategy_web_wrap(self, client: httpx.AsyncClient) -> list[dict[str, Any]]:
        """Dispatch wrapper: Web API / OAuth strategy."""
        return await self._primary_strategy(client)

    def _enrich_results(
        self,
        primary: list[dict[str, Any]] | None,
        enrichment: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        """Merge local session log enrichment into primary results."""
        if not enrichment or self._is_error_result(enrichment):
            return primary or []

        # Local-only host: promote fallback cards
        if not primary or self._is_error_result(primary):
            promoted = [e["_fallback_card"] for e in enrichment if e.get("_fallback_card")]
            return promoted or (primary or [])

        # Index enrichment by (variant, window_type)
        by_key = {
            (e.get("variant"), e.get("window_type")): e
            for e in enrichment
            if e.get("_enrichment_detail")
        }

        for card in primary:
            key = (card.get("variant"), card.get("window_type"))
            match = by_key.get(key)
            if not match:
                continue

            # Inject canonical enrichment fields
            for field in ("token_usage", "by_model", "msgs", "pct_used"):
                if field in match:
                    card[field] = match[field]

            # Append detail suffix
            suffix = match.get("_enrichment_detail", "")
            if suffix:
                card["detail"] = f"{card.get('detail', '').rstrip()} | {suffix}".strip(" |")

        return primary

    async def _error_handler(self) -> list[dict[str, Any]]:
        """Return final error card."""
        return [
            error_card("ChatGPT Codex", "💬", "No logs/auth found", error_type="missing_config")
        ]
