import asyncio
import httpx
from typing import List, Dict, Any
from app.services.collectors.anthropic import AnthropicCollector
from app.services.collectors.gemini import GeminiCollector
from app.services.collectors.github import GitHubCollector
from app.services.collectors.chatgpt import ChatGPTCollector
from app.services.collectors.antigravity import AntigravityCollector
from app.services.collectors.opencode import OpenCodeCollector
from app.services.collectors.chinese_ai import ChineseAICollector
from app.services.external_metrics import external_metric_service

class CollectorManager:
    def __init__(self):
        self.collectors = [
            AnthropicCollector(),
            GeminiCollector(),
            GitHubCollector(),
            ChatGPTCollector(),
            AntigravityCollector(),
            OpenCodeCollector(),
            ChineseAICollector()
        ]

    async def collect_all(self) -> List[Dict[str, Any]]:
        async with httpx.AsyncClient(timeout=15.0) as client:
            tasks = [collector.collect(client) for collector in self.collectors]
            results = await asyncio.gather(*tasks, return_exceptions=True)
        
        flattened = []
        for res in results:
            if isinstance(res, Exception):
                # Log exception but don't crash
                import logging
                logger = logging.getLogger(__name__)
                logger.error(f"Collector failed: {res}")
                continue
            if isinstance(res, list):
                flattened.extend(res)
        
        # Merge external metrics
        external_results = external_metric_service.get_all_metrics()
        flattened.extend(external_results)
        
        return flattened
