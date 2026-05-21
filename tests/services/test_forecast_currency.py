"""Unit tests for currency / credits cards in compute_forecast.

Currency and credits cards use the same quota-snapshot path as every other
unit type. These tests confirm status branches and field propagation for
non-percent, non-token unit types.
"""

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.db import QuotaSnapshot
from app.models.schemas import LimitCard
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
    provider_id: str = "anthropic",
    account_id: str = "acc1",
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
        provider_id=provider_id,
        account_id=account_id,
        pct_used=(
            pct_used
            if pct_used is not None
            else (used_value / limit_value * 100 if limit_value else 0.0)
        ),
        health="good",
        data_source="api",
    )


def _make_snapshot(
    *,
    session: Session,
    ts: datetime,
    pct_used: float,
    reset_at: datetime,
    provider_id: str = "anthropic",
    account_id: str = "acc1",
    window_type: str = "monthly",
    variant: str = "",
    model_id: str = "",
) -> QuotaSnapshot:
    snap = QuotaSnapshot(
        provider_id=provider_id,
        account_id=account_id,
        window_type=window_type,
        variant=variant,
        model_id=model_id,
        ts=ts,
        pct_used=pct_used,
        reset_at=reset_at,
    )
    session.add(snap)
    session.commit()
    return snap


class TestCurrencyInsufficientData:
    def test_no_snapshots_returns_insufficient_data(self, db_session):
        """No quota_snapshots at all → insufficient_data."""
        card = _make_currency_card(used_value=10.0, limit_value=100.0)
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status == "insufficient_data"
        assert result.samples_used == 0

    def test_single_bucket_returns_insufficient_data(self, db_session):
        """Three snapshots all within the same 6h bucket → samples_used=1 → insufficient_data."""
        now = datetime.now(UTC)
        reset_at_dt = now + timedelta(days=5)
        # Monthly window uses 6h buckets; 10-min spacing keeps all three in the same bucket.
        anchor = (now - timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)
        for i in range(3):
            _make_snapshot(
                session=db_session,
                ts=anchor + timedelta(minutes=i * 10),
                pct_used=10.0 + i,
                reset_at=reset_at_dt,
            )
        card = _make_currency_card(used_value=12.0, limit_value=100.0, reset_at=reset_at_dt)
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status == "insufficient_data"

    def test_unlimited_returns_none(self, db_session):
        """is_unlimited=True → compute_forecast returns None."""
        card = _make_currency_card(used_value=10.0, limit_value=100.0)
        unlimited_card = LimitCard(**{**card.model_dump(), "is_unlimited": True})
        result = compute_forecast(unlimited_card, db_session)
        assert result is None


class TestCurrencyStatusTransitions:
    def test_low_burn_is_ok(self, db_session):
        """Slow pct growth projecting below 80% by window end → ok."""
        now = datetime.now(UTC)
        reset_at_dt = now + timedelta(days=20)
        # 4 snapshots 6h apart → 4 distinct 6h buckets (monthly window)
        pct_values = [1.0, 1.5, 2.0, 2.5]
        for i, pct in enumerate(pct_values):
            _make_snapshot(
                session=db_session,
                ts=now - timedelta(hours=24 - i * 6),
                pct_used=pct,
                reset_at=reset_at_dt,
            )
        card = _make_currency_card(
            used_value=2.5,
            limit_value=100.0,
            pct_used=2.5,
            window_type="monthly",
            reset_at=reset_at_dt,
        )
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status == "ok"

    def test_steep_burn_is_risk(self, db_session):
        """Heavy pct growth projecting past 100% → risk (or warn/exhausted for edge cases)."""
        now = datetime.now(UTC)
        reset_at_dt = now + timedelta(days=5)
        pct_values = [20.0, 40.0, 60.0, 80.0]
        for i, pct in enumerate(pct_values):
            _make_snapshot(
                session=db_session,
                ts=now - timedelta(hours=24 - i * 6),
                pct_used=pct,
                reset_at=reset_at_dt,
            )
        card = _make_currency_card(
            used_value=80.0,
            limit_value=100.0,
            pct_used=80.0,
            window_type="monthly",
            reset_at=reset_at_dt,
        )
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status in ("risk", "warn", "exhausted")
        if result.status == "risk":
            assert result.projected_limit_hit_at is not None

    def test_near_exhaustion_status(self, db_session):
        """now_pct >= 99.9 with enough snapshot buckets → status=exhausted, projected_pct=100."""
        now = datetime.now(UTC)
        reset_at_dt = now + timedelta(days=10)
        pct_values = [90.0, 95.0, 98.0, 99.95]
        for i, pct in enumerate(pct_values):
            _make_snapshot(
                session=db_session,
                ts=now - timedelta(hours=24 - i * 6),
                pct_used=pct,
                reset_at=reset_at_dt,
            )
        card = _make_currency_card(
            used_value=99.95,
            limit_value=100.0,
            pct_used=99.95,
            window_type="monthly",
            reset_at=reset_at_dt,
        )
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status == "exhausted"
        assert result.projected_pct == 100.0


class TestCurrencyFields:
    def test_response_carries_window_metadata(self, db_session):
        """ForecastEntry carries correct window_type, unit_type, limit_value, reset_at."""
        now = datetime.now(UTC)
        reset_at_dt = now + timedelta(days=20)
        for i, pct in enumerate([1.0, 2.0, 3.0, 4.0]):
            _make_snapshot(
                session=db_session,
                ts=now - timedelta(hours=24 - i * 6),
                pct_used=pct,
                reset_at=reset_at_dt,
            )
        card = _make_currency_card(
            used_value=4.0,
            limit_value=100.0,
            pct_used=4.0,
            window_type="monthly",
            reset_at=reset_at_dt,
        )
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.window_type == "monthly"
        assert result.unit_type == "currency"
        assert result.limit_value == 100.0
        assert result.reset_at == card.reset_at
        assert 0.0 <= result.confidence <= 1.0
        assert result.samples_used >= 2

    def test_credits_unit_type_follows_same_path(self, db_session):
        """unit_type='credits' uses the same quota-snapshot path — returns non-None."""
        now = datetime.now(UTC)
        reset_at_dt = now + timedelta(days=20)
        for i, pct in enumerate([1.0, 2.0, 3.0, 4.0]):
            _make_snapshot(
                session=db_session,
                ts=now - timedelta(hours=24 - i * 6),
                pct_used=pct,
                reset_at=reset_at_dt,
            )
        card = _make_currency_card(
            used_value=4.0,
            limit_value=100.0,
            pct_used=4.0,
            unit_type="credits",
            window_type="monthly",
            reset_at=reset_at_dt,
        )
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.unit_type == "credits"


class TestCurrencyWindowBucketing:
    def test_daily_window_uses_finer_buckets(self, db_session):
        """Daily-window currency card: 4 snapshots each 1h apart → real forecast.

        Monthly uses 6h buckets; daily uses 30min buckets. 1h spacing puts each
        snapshot in a distinct 30min bucket, so samples_used == 4.
        """
        now = datetime(2026, 5, 20, 12, 0, 0, tzinfo=UTC)
        reset_at_dt = now + timedelta(hours=18)
        pct_values = [20.0, 35.0, 50.0, 65.0]
        for i, pct in enumerate(pct_values):
            _make_snapshot(
                session=db_session,
                ts=now - timedelta(hours=4 - i),
                pct_used=pct,
                reset_at=reset_at_dt,
                window_type="daily",
            )
        card = _make_currency_card(
            used_value=65.0,
            limit_value=100.0,
            pct_used=65.0,
            window_type="daily",
            reset_at=reset_at_dt,
        )
        result = compute_forecast(card, db_session, now=now)
        assert result is not None
        assert result.status != "insufficient_data"
        assert result.samples_used >= 4


class TestCurrencyAccountIsolation:
    def test_snapshots_for_other_account_dont_leak(self, db_session):
        """Snapshots for a different account_id must not contribute to this card's forecast."""
        now = datetime.now(UTC)
        reset_at_dt = now + timedelta(days=20)
        for i in range(4):
            _make_snapshot(
                session=db_session,
                ts=now - timedelta(hours=24 - i * 6),
                pct_used=10.0 * (i + 1),
                reset_at=reset_at_dt,
                account_id="other_acc",
            )
        card = _make_currency_card(used_value=2.0, limit_value=100.0, reset_at=reset_at_dt)
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status == "insufficient_data"
