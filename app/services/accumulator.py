# app/services/accumulator.py
from datetime import datetime, UTC
from sqlmodel import Session, select
from app.models.db import CumulativeUsage

class UsageAccumulator:
    def __init__(self, session: Session):
        self.session = session

    def process_delta(self, provider_id: str, account_id: str, sidecar_id: str, unit_type: str, delta_value: float, timestamp: str):
        if delta_value <= 0:
            return
            
        dt = datetime.fromisoformat(timestamp.replace('Z', '+00:00'))
        year_key = dt.strftime("%Y")
        month_key = dt.strftime("%Y-%m")

        periods = [
            ("lifetime", "all"),
            ("year", year_key),
            ("month", month_key)
        ]

        for p_type, p_key in periods:
            stmt = select(CumulativeUsage).where(
                CumulativeUsage.provider_id == provider_id,
                CumulativeUsage.account_id == account_id,
                CumulativeUsage.sidecar_id == sidecar_id,
                CumulativeUsage.period_type == p_type,
                CumulativeUsage.period_key == p_key,
                CumulativeUsage.unit_type == unit_type
            )
            record = self.session.exec(stmt).first()
            
            if not record:
                record = CumulativeUsage(
                    provider_id=provider_id,
                    account_id=account_id,
                    sidecar_id=sidecar_id,
                    period_type=p_type,
                    period_key=p_key,
                    unit_type=unit_type,
                    total_value=0.0
                )
                self.session.add(record)
            
            record.total_value += delta_value
            record.last_updated = datetime.now(UTC)
        
        self.session.commit()
