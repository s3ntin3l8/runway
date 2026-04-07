from fastapi import APIRouter
from app.models.schemas import LimitsResponse
from app.services.collector_manager import CollectorManager

router = APIRouter()
manager = CollectorManager()

@router.get("/limits", response_model=LimitsResponse)
async def fetch_all_limits():
    """Fetch all AI service usage limits."""
    results = await manager.collect_all()
    return {"limits": results}
