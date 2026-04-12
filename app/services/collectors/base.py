"""
Base collector class for all AI provider quota collectors.

This module defines the abstract interface that all provider-specific collectors
must implement. Each collector follows a 3-tier fallback pattern:
1. Primary Strategy: Direct API calls (OAuth, REST API, etc.)
2. Secondary Strategy: Local log parsing (CLI logs, cache files, etc.)
3. Tertiary Strategy: Error cards or graceful degradation
"""

import httpx
import logging
import asyncio
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Callable, Awaitable, Optional

logger = logging.getLogger(__name__)


class BaseCollector(ABC):
    """
    Abstract base class for all AI provider quota collectors.
    Now supports multi-account isolation.
    """

    def __init__(self, account_id: Optional[str] = None, account_name: Optional[str] = None):
        """
        Initialize BaseCollector.

        Args:
            account_id: Unique identifier for the account (None for default/ENV)
            account_name: Human-readable account name (e.g. email)
        """
        self.account_id = account_id
        self.account_name = account_name

    def _is_error_result(self, results: List[Dict[str, Any]]) -> bool:
        """Return True if results are empty or contain an error card."""
        return not results or any(r.get("remaining") == "ERR" for r in results)

    async def collect(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        """
        Orchestrate collection strategy with fallbacks and error handling.
        Automatically tags results with account identifiers.
        """
        try:
            # 1. Try Primary Strategy
            results = await self._primary_strategy(client)
            if not self._is_error_result(results):
                return self._tag_results(results)

            # 2. Try Fallbacks
            for strategy in self._fallback_strategies():
                try:
                    results = await strategy(client)
                    if not self._is_error_result(results):
                        return self._tag_results(results)
                except Exception as e:
                    logger.warning(f"Fallback strategy failed: {e}")

            # 3. All failed
            return self._tag_results(await self._error_handler())

        except Exception as e:
            logger.error(f"Collector {self.__class__.__name__} failed: {e}")
            return self._tag_results([
                {
                    "service": "Collector Error",
                    "icon": "⚠️",
                    "remaining": "ERR",
                    "unit": "fail",
                    "reset": "—",
                    "pace": "Stopped",
                    "detail": f"Internal Error: {str(e)[:30]}",
                    "health": "critical",
                }
            ])

    def _tag_results(self, results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Add account identifiers to every card in the result list.
        Also attempts to discover account_name if it is missing by scanning card details.
        """
        if not results:
            return []
        
        # 1. Try to discover account_name if missing
        if not self.account_name:
            import re
            for card in results:
                detail = card.get("detail", "")
                if not detail:
                    continue
                # Simple email/identity regex for discovery
                # Looks for email-like strings or "org: ..." patterns
                match = re.search(r"([a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,})", detail)
                if match:
                    self.account_name = match.group(1)
                    break
                
                # Fallback to org pattern or standalone username after separator (·)
                org_match = re.search(r"org:\s*([^\s·\[\]|]+)", detail)
                if org_match:
                    self.account_name = f"org: {org_match.group(1)}"
                    break
                
                # Standalone username after a dot/separator e.g. "· username"
                user_match = re.search(r"·\s*([a-zA-Z0-9_-]+)$", detail)
                if user_match:
                    self.account_name = user_match.group(1)
                    break

        # 2. Tag cards
        for card in results:
            if "account_id" not in card:
                card["account_id"] = self.account_id
            if "account_name" not in card or not card["account_name"]:
                card["account_name"] = self.account_name or "Default"
            
            # Final fallback: if account_name is still None/empty, set to "Default"
            if not card["account_name"]:
                card["account_name"] = "Default"
                
        return results

    @abstractmethod
    async def _primary_strategy(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        """Execute the primary (usually API) collection strategy."""
        pass

    @abstractmethod
    def _fallback_strategies(
        self,
    ) -> List[Callable[[httpx.AsyncClient], Awaitable[List[Dict[str, Any]]]]]:
        """Return an ordered list of fallback async methods to execute."""
        pass

    @abstractmethod
    async def _error_handler(self) -> List[Dict[str, Any]]:
        """Return the error card(s) when all strategies fail."""
        pass
