"""Integration tests for GET /api/v1/usage/forecast endpoint."""

import json
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine

from app.core.db import get_session
from app.main import app as fastapi_app
from app.models.db import LatestUsage


@pytest.fixture(name="session")
def session_fixture():
    # Use StaticPool to ensure all connections use the same in-memory DB
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(autouse=True)
def setup_api(session):
    fastapi_app.dependency_overrides[get_session] = lambda: session
    yield
    fastapi_app.dependency_overrides.clear()


def _add_latest(session: Session, **overrides):
    # Use a unique combination to avoid IntegrityError in same-session tests
    p_id = overrides.get("provider_id", f"anthropic_{overrides.get('service_name', 'default')}")
    card = {
        "service_name": overrides.get("service_name", "Test Service"),
        "provider_id": p_id,
        "account_id": overrides.get("account_id", "acc1"),
        "window_type": overrides.get("window_type", "weekly"),
        "unit_type": "tokens",
        "used_value": overrides.get("used_value", 500_000.0),
        "limit_value": overrides.get("limit_value", 1_000_000.0),
        "is_unlimited": overrides.get("is_unlimited", False),
        "reset_at": (datetime.now(UTC) + timedelta(days=4)).isoformat(),
        "health": "good",
    }
    record = LatestUsage(
        provider_id=card["provider_id"],
        account_id=card["account_id"],
        sidecar_id="local",
        window_type=card["window_type"],
        variant="default",
        card_json=json.dumps(card),
    )
    session.add(record)
    session.commit()


class TestForecastEndpoint:
    def test_forecast_endpoint_returns_200(self, session):
        _add_latest(session, service_name="Service A", account_id="acc1")
        _add_latest(session, service_name="Service B", account_id="acc2")

        client = TestClient(fastapi_app)
        response = client.get("/api/v1/usage/forecast")
        assert response.status_code == 200
        data = response.json()
        assert len(data["forecasts"]) == 2

    def test_forecast_endpoint_filters_by_provider_id(self, session):
        _add_latest(session, provider_id="p1")
        _add_latest(session, provider_id="p2")

        client = TestClient(fastapi_app)
        response = client.get("/api/v1/usage/forecast?provider_id=p1")
        assert len(response.json()["forecasts"]) == 1

    def test_forecast_endpoint_filters_by_window_type(self, session):
        _add_latest(session, window_type="weekly", service_name="W1")
        _add_latest(session, window_type="monthly", service_name="M1")

        client = TestClient(fastapi_app)
        response = client.get("/api/v1/usage/forecast?window_type=weekly")
        assert len(response.json()["forecasts"]) == 1

    def test_forecast_endpoint_filters_by_account_id(self, session):
        _add_latest(session, account_id="acc1", service_name="A1")
        _add_latest(session, account_id="acc2", service_name="A2")

        client = TestClient(fastapi_app)
        response = client.get("/api/v1/usage/forecast?account_id=acc1")
        assert len(response.json()["forecasts"]) == 1

    def test_forecast_endpoint_excludes_unlimited(self, session):
        _add_latest(session, service_name="Limited", is_unlimited=False)
        _add_latest(session, service_name="Unlimited", is_unlimited=True)

        client = TestClient(fastapi_app)
        response = client.get("/api/v1/usage/forecast")
        names = [f["service_name"] for f in response.json()["forecasts"]]
        assert "Limited" in names
        assert "Unlimited" not in names

    def test_forecast_endpoint_without_include_series_omits_series(self, session):
        _add_latest(session, service_name="Default")

        client = TestClient(fastapi_app)
        response = client.get("/api/v1/usage/forecast")
        for f in response.json()["forecasts"]:
            # Default path: series field should be null/missing for compact payloads.
            assert f.get("series") is None

    def test_forecast_endpoint_with_include_series_populates_for_eligible_cards(self, session):
        from app.models.db import UsageEvent

        # Card's weekly window opens 7 days before reset_at (which is now+4d),
        # so events need to land in [now-3d, now+4d]. Anchor at top of recent hours.
        now = datetime.now(UTC).replace(minute=0, second=0, microsecond=0)
        for i in range(4):
            session.add(
                UsageEvent(
                    provider_id="anthropic_Default",
                    account_id="acc1",
                    event_id=f"series_{i}",
                    ts=now - timedelta(hours=4 - i),
                    tokens_input=10_000,
                    tokens_output=5_000,
                    tokens_cache_read=0,
                    tokens_cache_create=0,
                    tokens_reasoning=0,
                    cost_usd=0.0,
                    sidecar_id="local",
                )
            )
        session.commit()
        _add_latest(session, service_name="Default", used_value=60_000.0)

        client = TestClient(fastapi_app)
        response = client.get("/api/v1/usage/forecast?include_series=true")
        forecasts = response.json()["forecasts"]
        # At least one card should have a populated series.
        assert any(f.get("series") for f in forecasts), forecasts

    def test_forecast_endpoint_exposes_glide_pct(self, session):
        """glide_pct must be present on every entry and equal confidence × 100."""
        import pytest

        _add_latest(session, service_name="Default")

        client = TestClient(fastapi_app)
        response = client.get("/api/v1/usage/forecast")
        forecasts = response.json()["forecasts"]
        assert forecasts, "expected at least one forecast entry"
        for f in forecasts:
            assert f.get("glide_pct") is not None, f
            assert 0.0 <= f["glide_pct"] <= 100.0
            assert f["glide_pct"] == pytest.approx(f["confidence"] * 100.0, abs=0.01)
