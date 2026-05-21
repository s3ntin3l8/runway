"""Tests for forecast service — percent and currency card branches."""

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


def _make_card(
    *,
    provider_id: str = "anthropic",
    account_id: str | None = "acc1",
    service_name: str = "Claude Pro",
    window_type: str = "weekly",
    unit_type: str = "tokens",
    unit: str = "tokens",
    used_value: float | None = 50_000.0,
    limit_value: float | None = 1_000_000.0,
    is_unlimited: bool = False,
    reset_at: str | None = None,
    pct_used: float | None = None,
    model_id: str | None = None,
) -> LimitCard:
    if reset_at is None:
        reset_at = (datetime.now(UTC) + timedelta(days=4)).isoformat()
    return LimitCard(
        service_name=service_name,
        unit=unit,
        unit_type=unit_type,
        used_value=used_value,
        limit_value=limit_value,
        is_unlimited=is_unlimited,
        reset_at=reset_at,
        window_type=window_type,
        provider_id=provider_id,
        account_id=account_id,
        model_id=model_id,
        health="good",
        data_source="api",
        pct_used=pct_used,
    )


def _make_snapshot(
    session: Session,
    *,
    ts: datetime,
    pct_used: float,
    reset_at: datetime,
    provider_id: str = "anthropic",
    account_id: str = "acc1",
    window_type: str = "weekly",
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


# ── Percent card tests ──────────────────────────────────────────────────────


class TestPercentForecast:
    def test_percent_card_with_no_events(self, db_session):
        """Percent card with no events → insufficient_data."""
        card = _make_card(
            unit_type="percent", unit="percent", used_value=42.0, limit_value=100.0, pct_used=42.0
        )
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status == "insufficient_data"

    def test_percent_card_returns_forecast_entry(self, db_session):
        """Percent card with pct_used set always returns a ForecastEntry (not None)."""
        now = datetime.now(UTC)
        reset_at = now + timedelta(days=3)
        card = _make_card(
            unit_type="percent",
            unit="percent",
            used_value=45.0,
            limit_value=100.0,
            pct_used=45.0,
            reset_at=reset_at.isoformat(),
        )
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status in ("ok", "warn", "risk", "stable", "insufficient_data")
        assert result.now_pct is not None

    def test_percent_card_high_usage_risk(self, db_session):
        """Percent card at 95% with growing quota snapshots → risk or warn."""
        now = datetime.now(UTC)
        reset_at_dt = now + timedelta(days=1)
        pct_values = [50.0, 65.0, 80.0, 95.0]
        for i, pct in enumerate(pct_values):
            _make_snapshot(
                db_session,
                ts=now - timedelta(hours=4 - i),
                pct_used=pct,
                reset_at=reset_at_dt,
            )
        card = _make_card(
            unit_type="percent",
            unit="percent",
            used_value=95.0,
            limit_value=100.0,
            pct_used=95.0,
            reset_at=reset_at_dt.isoformat(),
        )
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status in ("risk", "warn", "exhausted")

    def test_percent_card_stable(self, db_session):
        """Percent card at 10% with no events → insufficient_data (can't project)."""
        card = _make_card(
            unit_type="percent",
            unit="percent",
            used_value=10.0,
            limit_value=100.0,
            pct_used=10.0,
        )
        # No events → linear regression can't be built → insufficient_data
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status == "insufficient_data"


# ── Currency card tests ──────────────────────────────────────────────────────


class TestCurrencyForecast:
    def test_currency_card_with_no_rollups(self, db_session):
        """Currency card with no rollup data → insufficient_data."""
        card = _make_card(
            unit_type="currency",
            unit="USD",
            used_value=10.0,
            limit_value=100.0,
            pct_used=10.0,
        )
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status == "insufficient_data"

    def test_currency_card_returns_forecast_entry(self, db_session):
        """Currency card with pct_used always returns a ForecastEntry (not None)."""
        now = datetime.now(UTC)
        reset_at = now + timedelta(days=5)
        card = _make_card(
            unit_type="currency",
            unit="USD",
            used_value=10.0,
            limit_value=100.0,
            pct_used=10.0,
            reset_at=reset_at.isoformat(),
        )
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status in ("ok", "warn", "risk", "stable", "insufficient_data")

    def test_currency_card_spending_rapidly(self, db_session):
        """Currency card at $80/$100 with fast-growing quota snapshots → risk or warn."""
        now = datetime.now(UTC)
        reset_at_dt = now + timedelta(days=2)
        pct_values = [20.0, 40.0, 60.0, 80.0]
        for i, pct in enumerate(pct_values):
            _make_snapshot(
                db_session,
                ts=now - timedelta(hours=4 - i),
                pct_used=pct,
                reset_at=reset_at_dt,
                window_type="weekly",
            )
        card = _make_card(
            unit_type="currency",
            unit="USD",
            used_value=80.0,
            limit_value=100.0,
            pct_used=80.0,
            reset_at=reset_at_dt.isoformat(),
        )
        result = compute_forecast(card, db_session)
        assert result is not None
        assert result.status in ("risk", "warn", "exhausted")


# ── Dispatch and edge cases ─────────────────────────────────────────────────


class TestForecastDispatch:
    def test_token_singular_normalizes(self, db_session):
        """unit_type='token' (singular) should be handled like 'tokens'."""
        card = _make_card(
            unit_type="token", unit="tokens", used_value=50_000.0, limit_value=1_000_000.0
        )
        result = compute_forecast(card, db_session)
        # Should not be None — 'token' is normalized to 'tokens'
        assert result is not None
        assert result.status == "insufficient_data"  # No events

    def test_rolling_window_type_supported(self, db_session):
        """window_type='rolling' should be supported (mapped to monthly duration)."""
        card = _make_card(
            unit_type="tokens",
            window_type="rolling",
            used_value=50_000.0,
            limit_value=1_000_000.0,
        )
        result = compute_forecast(card, db_session)
        assert result is not None
        # Should not be None — rolling windows are now supported

    def test_requests_unit_type_is_forecastable(self, db_session):
        """unit_type='requests' has a derivable pct — quota-snapshot path handles it."""
        card = _make_card(
            unit_type="requests", unit="requests", used_value=50.0, limit_value=1000.0
        )
        result = compute_forecast(card, db_session)
        # No snapshots → insufficient_data; but not None (pct is derivable from used/limit).
        assert result is not None
        assert result.status == "insufficient_data"
