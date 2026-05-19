"""Targeted tests for the Phase 2 algorithm changes: Theil-Sen robustness,
horizon cap on projected_limit_hit_at, and the decelerating status."""

from datetime import UTC, datetime, timedelta

import pytest
from sqlmodel import Session, SQLModel, create_engine

from app.models.db import UsageEvent
from app.models.schemas import LimitCard
from app.services.forecast import _fit_trend, compute_forecast


@pytest.fixture
def db_session(mock_db_session):
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False})
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _make_card(
    *,
    used_value: float,
    limit_value: float,
    reset_at: datetime,
    window_type: str = "weekly",
) -> LimitCard:
    return LimitCard(
        service_name="Test",
        unit="tokens",
        unit_type="tokens",
        used_value=used_value,
        limit_value=limit_value,
        is_unlimited=False,
        reset_at=reset_at.isoformat(),
        window_type=window_type,
        provider_id="anthropic",
        account_id="acc1",
        health="good",
        data_source="api",
    )


def _make_event(session, *, ts, tokens_input, event_id_suffix):
    event = UsageEvent(
        provider_id="anthropic",
        account_id="acc1",
        event_id=f"evt_{ts.isoformat()}_{event_id_suffix}",
        ts=ts,
        tokens_input=tokens_input,
        tokens_output=0,
        tokens_cache_read=0,
        tokens_cache_create=0,
        tokens_reasoning=0,
        cost_usd=0.0,
        sidecar_id="local",
    )
    session.add(event)
    session.commit()


class TestTheilSenEstimator:
    def test_perfect_linear_data_matches_ols(self):
        """On clean linear data, Theil-Sen and OLS produce the same fit."""
        xs = [0.0, 3600.0, 7200.0, 10800.0]
        ys = [10.0, 30.0, 50.0, 70.0]
        fit = _fit_trend(xs, ys)
        assert fit is not None
        assert fit.method == "theil_sen"
        assert fit.slope == pytest.approx(20.0 / 3600.0, rel=1e-9)
        assert fit.intercept == pytest.approx(10.0, abs=1e-9)

    def test_single_outlier_does_not_drag_slope(self):
        """A 10× spike at one bucket must not significantly shift the slope."""
        # Clean slope = 5 pct/hr = 5/3600 pct/sec
        clean_xs = [i * 3600.0 for i in range(8)]
        clean_ys = [5.0 * (i + 1) for i in range(8)]
        clean = _fit_trend(clean_xs, clean_ys)
        assert clean is not None

        # Inject a 10× spike at index 4 — y jumps from 25 to 250 then resumes.
        spiky_ys = clean_ys.copy()
        spiky_ys[4] = 250.0
        spiky_ys[5] = 30.0
        spiky_ys[6] = 35.0
        spiky_ys[7] = 40.0
        spiky = _fit_trend(clean_xs, spiky_ys)
        assert spiky is not None

        # Theil-Sen median-of-pairwise-slopes is robust: a single outlier
        # shouldn't more than double the slope estimate (OLS would explode).
        assert spiky.slope == pytest.approx(clean.slope, rel=0.5)

    def test_below_min_buckets_returns_none(self):
        """Fewer than MIN_BUCKETS_FOR_TREND points → no fit."""
        assert _fit_trend([0.0, 3600.0], [10.0, 20.0]) is None
        assert _fit_trend([0.0, 3600.0, 7200.0], [10.0, 20.0, 30.0]) is None


class TestHorizonCap:
    def test_anchored_projection_below_limit_yields_no_hit_at(self, db_session):
        """Under anchor-at-now projection, slope too small to cross 100% within
        remaining time → no hit_at, status is not risk."""
        window_start = datetime(2026, 5, 12, 0, 0, 0, tzinfo=UTC)
        now = window_start + timedelta(hours=23)
        reset_at = window_start + timedelta(hours=24)
        limit = 1_000_000

        # Gentle, perfectly linear growth: 1000 tokens/hour for 5 buckets.
        # now_pct ≈ 0.5%. With 1h remaining and tiny slope, projected ≪ 100%.
        for i in range(5):
            ts = window_start + timedelta(hours=i)
            _make_event(db_session, ts=ts, tokens_input=1_000, event_id_suffix=f"gentle_{i}")

        card = _make_card(used_value=5_000.0, limit_value=float(limit), reset_at=reset_at)
        result = compute_forecast(card, db_session, now=now)
        assert result is not None
        # Projection well below 100 → no hit_at, status is ok/stable.
        assert result.projected_limit_hit_at is None
        assert result.status in ("ok", "stable")


class TestDeceleratingStatus:
    def test_high_usage_with_dipping_projection_decelerates(self, db_session):
        """At 95% with regression projecting below current → decelerating."""
        window_start = datetime(2026, 5, 13, 0, 0, 0, tzinfo=UTC)
        now = window_start + timedelta(days=6, hours=12)
        reset_at = window_start + timedelta(days=7)
        limit = 1000

        # Back-loaded: tiny daily then big final → regression line ends below current.
        chunks = [50, 10, 10, 10, 10, 10, 850]
        for i, chunk in enumerate(chunks):
            ts = window_start + timedelta(days=i)
            _make_event(db_session, ts=ts, tokens_input=chunk, event_id_suffix=f"dec_{i}")

        card = _make_card(used_value=950.0, limit_value=float(limit), reset_at=reset_at)
        result = compute_forecast(card, db_session, now=now)
        assert result is not None
        assert result.status == "decelerating"

    def test_low_usage_decelerating_does_not_fire(self, db_session):
        """At 40% (below DECELERATING_NOW_PCT_THRESHOLD), the same dipping
        projection produces 'stable' or 'ok' — not 'decelerating'."""
        window_start = datetime(2026, 5, 13, 0, 0, 0, tzinfo=UTC)
        now = window_start + timedelta(days=6, hours=12)
        reset_at = window_start + timedelta(days=7)
        limit = 1000

        # Same dipping pattern at lower magnitude → now_pct=40.
        chunks = [20, 4, 4, 4, 4, 4, 360]  # cumulative 400 = 40%
        for i, chunk in enumerate(chunks):
            ts = window_start + timedelta(days=i)
            _make_event(db_session, ts=ts, tokens_input=chunk, event_id_suffix=f"low_{i}")

        card = _make_card(used_value=400.0, limit_value=float(limit), reset_at=reset_at)
        result = compute_forecast(card, db_session, now=now)
        assert result is not None
        # Not in matters-zone → decelerating doesn't fire.
        assert result.status != "decelerating"

    def test_exhausted_wins_over_decelerating(self, db_session):
        """At 99.95%, status=exhausted regardless of slope direction."""
        window_start = datetime(2026, 5, 13, 0, 0, 0, tzinfo=UTC)
        now = window_start + timedelta(days=6, hours=12)
        reset_at = window_start + timedelta(days=7)
        limit = 1000

        chunks = [50, 10, 10, 10, 10, 10, 900]  # cumulative ~999 ≈ 99.9%+
        for i, chunk in enumerate(chunks):
            ts = window_start + timedelta(days=i)
            _make_event(db_session, ts=ts, tokens_input=chunk, event_id_suffix=f"exh_{i}")

        card = _make_card(used_value=999.5, limit_value=float(limit), reset_at=reset_at)
        result = compute_forecast(card, db_session, now=now)
        assert result is not None
        assert result.status == "exhausted"
