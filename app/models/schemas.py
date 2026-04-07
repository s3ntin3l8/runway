from typing import List, Optional
from pydantic import BaseModel

class LimitCard(BaseModel):
    service: str
    icon: str
    remaining: str
    unit: str
    reset: str
    health: str
    pace: str
    detail: str

class LimitsResponse(BaseModel):
    limits: List[LimitCard]

class IngestRequest(BaseModel):
    provider: str
    metrics: List[LimitCard]
    api_key: str
