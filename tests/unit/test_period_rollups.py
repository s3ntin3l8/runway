from datetime import UTC, datetime

from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.models.db import UsageEvent, UsagePeriodRollup
from app.services.period_rollups import update_rollups_for_event


def _session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_single_event_creates_grain_rows():
    """One event creates 4 rollup rows per period: ('',''), (model,''), ('',sidecar), (model,sidecar)."""
    s = _session()
    e = UsageEvent(
        provider_id="anthropic",
        account_id="user@x.com",
        sidecar_id="dev-01",
        event_id="msg_1",
        ts=datetime(2026, 5, 8, 14, 23, tzinfo=UTC),
        model_id="sonnet",
        tokens_input=100,
        tokens_output=200,
        tokens_cache_read=0,
        tokens_cache_create=0,
        tokens_reasoning=0,
        cost_usd=0.018,
    )
    s.add(e)
    s.commit()
    s.refresh(e)
    update_rollups_for_event(s, e)

    rows = s.exec(select(UsagePeriodRollup)).all()
    # Periods: hour, day, month, year, lifetime = 5
    # Grains per period: ('',''), ('sonnet',''), ('','dev-01'), ('sonnet','dev-01') = 4
    # Total = 20
    assert len(rows) == 20


def test_two_events_same_period_increment():
    s = _session()
    for i in range(2):
        e = UsageEvent(
            provider_id="anthropic",
            account_id="user@x.com",
            sidecar_id="dev-01",
            event_id=f"msg_{i}",
            ts=datetime(2026, 5, 8, 14, 23, tzinfo=UTC),
            model_id="sonnet",
            tokens_input=100,
            tokens_output=200,
        )
        s.add(e)
        s.commit()
        s.refresh(e)
        update_rollups_for_event(s, e)

    row = s.exec(
        select(UsagePeriodRollup).where(
            UsagePeriodRollup.provider_id == "anthropic",
            UsagePeriodRollup.account_id == "user@x.com",
            UsagePeriodRollup.period_type == "day",
            UsagePeriodRollup.period_key == "2026-05-08",
            UsagePeriodRollup.model_id == "",
            UsagePeriodRollup.sidecar_id == "",
        )
    ).first()
    assert row.tokens_input == 200
    assert row.tokens_output == 400
    assert row.msgs == 2
