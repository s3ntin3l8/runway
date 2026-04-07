import httpx
from abc import ABC, abstractmethod
from typing import List, Dict, Any
from app.models.schemas import LimitCard

class BaseCollector(ABC):
    @abstractmethod
    async def collect(self, client: httpx.AsyncClient) -> List[Dict[str, Any]]:
        """Collect usage limits and return a list of result dictionaries."""
        pass
