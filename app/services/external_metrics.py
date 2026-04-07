import json
import os
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any
from app.core.config import settings
from app.models.schemas import LimitCard

logger = logging.getLogger(__name__)

class ExternalMetricService:
    def __init__(self):
        self.path = settings.EXTERNAL_METRICS_PATH
        self._ensure_dir()
        self.metrics: Dict[str, Dict[str, Any]] = self._load()

    def _ensure_dir(self):
        dir_path = os.path.dirname(self.path)
        if not os.path.exists(dir_path):
            os.makedirs(dir_path, exist_ok=True)

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if os.path.exists(self.path):
            try:
                with open(self.path, "r") as f:
                    return json.load(f)
            except FileNotFoundError:
                logger.debug(f"External metrics file not found: {self.path}")
                return {}
            except json.JSONDecodeError:
                logger.warning(f"Invalid JSON in external metrics file: {self.path}")
                return {}
            except Exception as e:
                logger.error(f"Failed to load external metrics: {e}")
                return {}
        return {}

    def _save(self):
        with open(self.path, "w") as f:
            json.dump(self.metrics, f, indent=2)

    def update_metrics(self, provider: str, cards: List[LimitCard]):
        now = datetime.now(timezone.utc).isoformat()
        processed_cards = []
        for card in cards:
            card_dict = card.model_dump()
            # Append update info to detail
            card_dict["detail"] += f" [Sidecar Updated: {datetime.now(timezone.utc).strftime('%H:%M:%S')}]"
            processed_cards.append(card_dict)
            
        self.metrics[provider] = {
            "timestamp": now,
            "cards": processed_cards
        }
        self._save()

    def get_all_metrics(self) -> List[Dict[str, Any]]:
        all_cards = []
        now = datetime.now(timezone.utc)
        for provider, data in self.metrics.items():
            ts = datetime.fromisoformat(data["timestamp"])
            diff = now - ts
            minutes = int(diff.total_seconds() / 60)
            
            time_str = f"{minutes}m ago" if minutes > 0 else "just now"
            
            for card in data["cards"]:
                updated_card = card.copy()
                updated_card["service"] += f" ({time_str})"
                all_cards.append(updated_card)
        return all_cards

# Global instance
external_metric_service = ExternalMetricService()
