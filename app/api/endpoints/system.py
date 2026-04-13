from fastapi import APIRouter, Request
from typing import Dict, Any
import time
import logging

from app.core.config import settings
from app.core.encryption import encryption_service
from app.core.rate_limit import limiter
from app.services.collector_manager import manager

logger = logging.getLogger(__name__)
router = APIRouter()


@router.get("/health")
@limiter.limit("30/minute")
async def health_check(request: Request) -> Dict[str, Any]:
    """Check system health and collector status."""
    return {
        "status": "healthy",
        "timestamp": time.time(),
    }


@router.get("/settings")
@limiter.limit("30/minute")
async def get_app_settings(request: Request) -> Dict[str, Any]:
    """Return the current non-sensitive configuration."""
    return {
        "project_name": settings.PROJECT_NAME,
        "run_mode": settings.RUN_MODE,
        "app_host": settings.APP_HOST,
        "app_port": settings.APP_PORT,
        "encryption_enabled": encryption_service.is_enabled,
        "local_collector_enabled": settings.LOCAL_COLLECTOR_ENABLED,
        "local_credential_scraping": settings.LOCAL_CREDENTIAL_SCRAPING_ENABLED,
        "ingest_api_key_is_default": settings.INGEST_API_KEY_IS_INSECURE_DEFAULT,
    }


@router.get("/status")
@limiter.limit("30/minute")
async def get_collector_status(request: Request) -> Dict[str, Any]:
    """Return detailed health and cache stats for all active collectors."""
    try:
        await manager._sync_collectors()
    except Exception as e:
        logger.error(f"Failed to sync collectors for status: {e}")
    return manager.get_collector_stats()
