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
        async with httpx.AsyncClient() as client:
            tasks = [collector.collect(client) for collector in self.collectors]
            results = await asyncio.gather(*tasks)
        
        flattened = []
        for res in results:
            if isinstance(res, list):
                flattened.extend(res)
        return flattened
