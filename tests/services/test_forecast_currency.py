"""Comprehensive unit tests for the currency/credits branch of compute_forecast.

These tests pin observable behavior of `_compute_currency_forecast` before
the Phase 1 refactor and Phase 2 algorithm changes, so regressions surface.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.db import UsagePeriodRollup
from app.models.schemas import LimitCard
from app.services.forecast import MIN_BUCKETS_FOR_TREND as MIN_BUCKETS_FOR_TREND_VALUE
from app.services.forecast import compute_forecast


@pytest.fixture
def db_session(mock_db_session):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_currency_card(
    *,
    used_value: float = 10.0,
    limit_value: float = 100.0,
    pct_used: float | None = None,
    window_type: str = "monthly",
    reset_at: datetime | None = None,
    unit_type: str = "currency",
) -> LimitCard:
    reset = reset_at or (datetime.now(UTC) + timedelta(days=5))
    return LimitCard(
        service_name="Test API",
        unit="USD",
        unit_type=unit_type,
        used_value=used_value,
        limit_value=limit_value,
        is_unlimited=False,
        reset_at=reset.isoformat(),
        window_type=window_type,
        provider_id="anthropic",
        account_id="acc1",
        pct_used=(
            pct_used
            if pct_used is not None
            else (used_value / limit_value * 100 if limit_value else 0.0)
        ),
        health="good",
        data_source="api",
    )


def _seed_daily(
    session: Session,
    *,
    period_key: str,
    cost_usd: float,
    provider_id: str = "anthropic",
    account_id: str = "acc1",
) -> None:
    r = UsagePeriodRollup(
        provider_id=provider_id,
        account_id=account_id,
        period_type="day",
        period_key=period_key,
        model_id="",
        sidecar_id="",
        tokens_input=0,
        tokens_output=0,
        tokens_cache_read=0,
        tokens_cache_create=0,
        tokens_reasoning=0,
        cost_usd=cost_usd,
        msgs=1,
    )
    session.add(r)
    session.commit()


class TestCurrencyInsufficientData:
    def test_no_rollups_returns_insufficient_data(self, db_session):
        card = _make_currency_card(used_value=10.0, limit_value=100.0)
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status == "insufficient_data"
        assert result.samples_used == 0

    def test_single_rollup_returns_insufficient_data(self, db_session):
        now = datetime.now(UTC)
        _seed_daily(
            db_session,
            period_key=(now - timedelta(days=1)).strftime("%Y-%m-%d"),
            cost_usd=5.0,
        )
        card = _make_currency_card(used_value=5.0, limit_value=100.0)
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status == "insufficient_data"

    def test_zero_limit_returns_none(self, db_session):
        """Dispatcher short-circuits on limit_value=0 for non-percent unit types."""
        card = _make_currency_card(used_value=0.0, limit_value=0.0)
        result = compute_forecast(card, db_session)
        assert result is None


class TestCurrencyStatusTransitions:
    def test_low_burn_is_ok(self, db_session):
        """Modest burn projecting under 80% → ok."""
        now = datetime.now(UTC)
        reset_at = now + timedelta(days=20)
        # 5 days of $0.50/day → projected total over 30 days ≈ $15 → 15% of $100
        for i in range(5):
            day = (now - timedelta(days=5 - i)).strftime("%Y-%m-%d")
            _seed_daily(db_session, period_key=day, cost_usd=0.50)
        card = _make_currency_card(
            used_value=2.5,
            limit_value=100.0,
            window_type="monthly",
            reset_at=reset_at,
        )
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status == "ok"

    def test_steep_burn_is_risk(self, db_session):
        """Heavy burn projecting past 100% → risk with hit_at populated."""
        now = datetime.now(UTC)
        reset_at = now + timedelta(days=5)
        for i in range(5):
            day = (now - timedelta(days=5 - i)).strftime("%Y-%m-%d")
            _seed_daily(db_session, period_key=day, cost_usd=10.00)
        card = _make_currency_card(
            used_value=50.0,
            limit_value=100.0,
            window_type="monthly",
            reset_at=reset_at,
        )
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status in ("risk", "warn", "exhausted")
        if result.status == "risk":
            assert result.projected_limit_hit_at is not None

    def test_near_exhaustion_status(self, db_session):
        """now_pct >= 99.9 → status=exhausted regardless of slope."""
        now = datetime.now(UTC)
        reset_at = now + timedelta(days=10)
        for i in range(4):
            day = (now - timedelta(days=4 - i)).strftime("%Y-%m-%d")
            _seed_daily(db_session, period_key=day, cost_usd=25.00)
        card = _make_currency_card(
            used_value=99.95,
            limit_value=100.0,
            window_type="monthly",
            reset_at=reset_at,
        )
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status == "exhausted"
        # When exhausted, projected_pct is pinned to 100
        assert result.projected_pct == 100.0


class TestCurrencyFields:
    def test_response_carries_window_metadata(self, db_session):
        now = datetime.now(UTC)
        reset_at = now + timedelta(days=20)
        for i in range(4):
            day = (now - timedelta(days=4 - i)).strftime("%Y-%m-%d")
            _seed_daily(db_session, period_key=day, cost_usd=1.0)
        card = _make_currency_card(
            used_value=4.0,
            limit_value=100.0,
            window_type="monthly",
            reset_at=reset_at,
        )
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.window_type == "monthly"
        assert result.unit_type == "currency"
        assert result.limit_value == 100.0
        assert result.reset_at == card.reset_at
        assert 0.0 <= result.confidence <= 1.0
        assert result.samples_used >= 2

    def test_credits_unit_type_dispatches_to_currency(self, db_session):
        """unit_type='credits' should be handled by _compute_currency_forecast."""
        now = datetime.now(UTC)
        reset_at = now + timedelta(days=20)
        for i in range(4):
            day = (now - timedelta(days=4 - i)).strftime("%Y-%m-%d")
            _seed_daily(db_session, period_key=day, cost_usd=1.0)
        card = _make_currency_card(
            used_value=4.0,
            limit_value=100.0,
            unit_type="credits",
            window_type="monthly",
            reset_at=reset_at,
        )
        result = compute_forecast(card, db_session)
        assert result is not None
        # Same code path → should produce a non-None ForecastEntry, not return None.
        assert result.unit_type == "credits"


class TestCurrencyShortWindowGranularity:
    def test_daily_window_uses_hourly_buckets(self, db_session):
        """A daily-window currency card with hourly events should produce a real forecast,
        not insufficient_data. Phase 2: short windows bucket on usage_events directly."""
        from app.models.db import UsageEvent

        window_start = datetime(2026, 5, 18, 0, 0, 0, tzinfo=UTC)
        now = window_start + timedelta(hours=6)
        reset_at = window_start + timedelta(hours=24)

        # 6 hourly events with cost_usd, total ≈ $4.50 (45% of $10 limit)
        for i in range(6):
            ts = window_start + timedelta(hours=i)
            event = UsageEvent(
                provider_id="anthropic",
                account_id="acc1",
                event_id=f"hourly_{i}",
                ts=ts,
                tokens_input=1_000,
                tokens_output=500,
                tokens_cache_read=0,
                tokens_cache_create=0,
                tokens_reasoning=0,
                cost_usd=0.75,
                sidecar_id="local",
            )
            db_session.add(event)
        db_session.commit()

        card = _make_currency_card(
            used_value=4.5,
            limit_value=10.0,
            window_type="daily",
            reset_at=reset_at,
        )
        result = compute_forecast(card, db_session, now=now)
        assert result is not None
        assert result.status != "insufficient_data"
        assert result.samples_used >= MIN_BUCKETS_FOR_TREND_VALUE


class TestCurrencyAccountIsolation:
    def test_rollups_for_other_account_dont_leak(self, db_session):
        """Rollups for a different account_id must not contribute to this card's forecast."""
        now = datetime.now(UTC)
        reset_at = now + timedelta(days=20)
        # Seed for a foreign account
        for i in range(5):
            day = (now - timedelta(days=5 - i)).strftime("%Y-%m-%d")
            _seed_daily(db_session, period_key=day, cost_usd=99.0, account_id="other_acc")
        # No rollups for acc1
        card = _make_currency_card(used_value=2.0, limit_value=100.0, reset_at=reset_at)
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status == "insufficient_data"
