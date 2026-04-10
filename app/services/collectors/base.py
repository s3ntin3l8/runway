"""
Base collector class for all AI provider quota collectors.

This module defines the abstract interface that all provider-specific collectors
must implement. Each collector follows a 3-tier fallback pattern:
1. Primary Strategy: Direct API calls (OAuth, REST API, etc.)
2. Secondary Strategy: Local log parsing (CLI logs, cache files, etc.)
3. Tertiary Strategy: Error cards or graceful degradation

The collector pattern ensures resilience in headless environments (Docker, CI/CD)
where desktop UI features may not be available.
"""

import httpx
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from app.models.schemas import LimitCard


class BaseCollector(ABC):
    """
    Abstract base class for all AI provider quota collectors.

    Defines the interface that all provider-specific collectors must implement.
    Collectors are responsible for:
    - Fetching quota and usage data from their respective providers
    - Implementing resilient fallback strategies when APIs are unavailable
    - Returning standardized LimitCard dictionaries for frontend rendering

    The collect() method should be idempotent and handle errors gracefully,
    returning error cards instead of raising exceptions.
    """

    def _is_error_result(self, results: List[Dict[str, Any]]) -> bool:
        """Return True if results are empty or contain an error card."""
        return not results or any(r.get("remaining") == "ERR" for r in results)

    async def collect(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        """
        Automated Strategy Pattern orchestration. Executes defined strategies
        sequentially until one succeeds or all fail.
        """
        strategies = self._get_strategies()
        
        for strategy in strategies:
            try:
                results = await strategy(client)
                if not self._is_error_result(results):
                    # Success! Return the results immediately
                    return results
                
                # If we got an error result, continue to the next fallback strategy
                strategy_name = strategy.__name__ if hasattr(strategy, '__name__') else "unknown"
                import logging
                logging.getLogger(__name__).debug(f"Strategy {strategy_name} returned error/empty, falling back...")
                
            except Exception as e:
                # Catch all strategy failures and move to next fallback
                strategy_name = strategy.__name__ if hasattr(strategy, '__name__') else "unknown"
                import logging
                logging.getLogger(__name__).warning(f"Strategy {strategy_name} raised exception: {e}")
        
        # All strategies failed - return the final fallback error
        return await self._get_fallback_error()

    @abstractmethod
    def _get_strategies(self) -> List[Any]:
        """
        Return an ordered list of async methods (strategies) to execute.
        Expected order: Primary (API) -> Secondary (Web) -> Tertiary (Logs).
        """
        pass

    @abstractmethod
    async def _get_fallback_error(self) -> List[Dict[str, Any]]:
        """
        Return the ultimate error card(s) to display when all strategies fail.
        """
        pass

