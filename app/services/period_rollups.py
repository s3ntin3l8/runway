"""Incremental upsert into usage_period_rollup per event."""

from datetime import UTC, datetime

from sqlmodel import Session, select

from app.models.db import UsageEvent, UsagePeriodRollup


def _period_keys(ts: datetime) -> list[tuple[str, str]]:
    """Return (period_type, period_key) tuples for a given event timestamp."""
    return [
        ("hour", ts.strftime("%Y-%m-%dT%H")),
        ("day", ts.strftime("%Y-%m-%d")),
        ("month", ts.strftime("%Y-%m")),
        ("year", ts.strftime("%Y")),
        ("lifetime", "all"),
    ]


def update_rollups_for_event(session: Session, ev: UsageEvent) -> None:
    """Increment the 4 grain rows × 5 periods = 20 rows for this event.

    Grains are: ('',''), (model_id,''), ('',sidecar_id), (model_id,sidecar_id).
    When model_id is empty/None, the 4-grain list deduplicates to 2 unique
    grains — ('','') and ('',sidecar_id) — so empty-model rows merge correctly.
    """
    grains: list[tuple[str, str]] = [
        ("", ""),
        (ev.model_id or "", ""),
        ("", ev.sidecar_id or ""),
        (ev.model_id or "", ev.sidecar_id or ""),
    ]
    # dedupe in case model_id is empty (then ('','') and (model,'') collide)
    seen_grains: dict[tuple[str, str], None] = {}
    for g in grains:
        seen_grains[g] = None
    unique_grains = list(seen_grains.keys())

    for period_type, period_key in _period_keys(ev.ts):
        for model_id, sidecar_id in unique_grains:
            row = session.exec(
                select(UsagePeriodRollup).where(
                    UsagePeriodRollup.provider_id == ev.provider_id,
                    UsagePeriodRollup.account_id == ev.account_id,
                    UsagePeriodRollup.period_type == period_type,
                    UsagePeriodRollup.period_key == period_key,
                    UsagePeriodRollup.model_id == model_id,
                    UsagePeriodRollup.sidecar_id == sidecar_id,
                )
            ).first()
            if row is None:
                row = UsagePeriodRollup(
                    provider_id=ev.provider_id,
                    account_id=ev.account_id,
                    period_type=period_type,
                    period_key=period_key,
                    model_id=model_id,
                    sidecar_id=sidecar_id,
                )
                session.add(row)
            row.msgs += 1
            row.tokens_input += ev.tokens_input
            row.tokens_output += ev.tokens_output
            row.tokens_cache_read += ev.tokens_cache_read
            row.tokens_cache_create += ev.tokens_cache_create
            row.tokens_reasoning += ev.tokens_reasoning
            row.cost_usd += ev.cost_usd
            row.last_updated = datetime.now(UTC)
    session.commit()
