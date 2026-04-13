import asyncio
import logging
from datetime import datetime, timezone
from sqlmodel import Session
from app.services.collector_manager import manager
from app.core.db import engine
from app.models.db import UsageSnapshot
from app.models.schemas import LimitCard
from typing import List, Optional

logger = logging.getLogger(__name__)

_COMPACTION_INTERVAL_POLLS = 96  # 96 × 15 min = 24 hours


class BackgroundPoller:
    def __init__(self, interval_seconds: int = 900): # Default 15 minutes
        self.interval = interval_seconds
        self._task: Optional[asyncio.Task] = None
        self._running = False
        self._poll_count = 0  # tracks polls for daily compaction trigger

    def start(self):
        """Start the background polling task."""
        if self._task is not None:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"Background poller started with {self.interval}s interval.")

    async def stop(self):
        """Stop the background polling task."""
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
            self._task = None
        logger.info("Background poller stopped.")

    async def _run_loop(self):
        while self._running:
            await asyncio.sleep(self.interval)
            if not self._running:
                break
            try:
                await self.poll_now()
            except Exception as e:
                logger.error(f"Error during background poll: {e}")

    async def poll_now(self):
        """Execute a single collection and snapshot cycle."""
        logger.info("Starting scheduled background collection...")
        cards = await manager.collect_all()

        if not cards:
            logger.debug("No metrics collected during background poll.")
        else:
            with Session(engine) as session:
                for card_dict in cards:
                    try:
                        card = LimitCard(**card_dict)
                        if not card.provider_id or not card.account_id:
                            continue
                        if card.data_source == "cache":
                            continue
                        snapshot = UsageSnapshot(
                            provider_id=card.provider_id,
                            account_id=card.account_id,
                            account_label=card.account_label,
                            service_name=card.service_name,
                            used_value=card.used_value,
                            limit_value=card.limit_value,
                            unit_type=card.unit_type,
                            currency=card.currency,
                            tier=card.tier,
                            model_id=card.model_id,
                            window_type=card.window_type,
                            health=card.health,
                            sidecar_id=card.sidecar_id,
                            is_unlimited=card.is_unlimited,
                            data_source=card.data_source,
                            error_type=card.error_type,
                            timestamp=datetime.now(timezone.utc),
                        )
                        snapshot.raw_metadata = card.metadata
                        session.add(snapshot)
                    except Exception as e:
                        logger.error(f"Failed to map card to snapshot: {e}")

                session.commit()
                logger.info(f"Background poll complete. Snapshotted {len(cards)} metrics.")

        # Always count this poll, even if no data was collected
        self._poll_count += 1
        if self._poll_count % _COMPACTION_INTERVAL_POLLS == 0:
            try:
                from app.services.compaction import compact_snapshots
                with Session(engine) as compact_session:
                    result = compact_snapshots(compact_session)
                    logger.info(f"Daily compaction result: {result}")
            except Exception as e:
                logger.error(f"Compaction failed (non-fatal): {e}")

# Global instance
poller = BackgroundPoller()
