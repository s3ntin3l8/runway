from fastapi import APIRouter, HTTPException
from datetime import datetime, timezone
from app.models.schemas import IngestRequest
from app.services.external_metrics import external_metric_service
from app.core.config import settings

router = APIRouter()

@router.post("/ingest")
async def ingest_metrics(request: IngestRequest):
    if request.api_key != settings.INGEST_API_KEY:
        raise HTTPException(status_code=401, detail="Invalid API Key")
    
    external_metric_service.metrics[request.provider] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "cards": [card.model_dump() for card in request.metrics]
    }
    external_metric_service._save()
    return {"status": "ok", "provider": request.provider}
