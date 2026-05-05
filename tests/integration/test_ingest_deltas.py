"""Integration test: /api/v1/fleet/ingest accepts deltas[] and feeds CumulativeUsage."""

import hashlib
import hmac
import json
import time
from unittest.mock import AsyncMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from app.core.db import get_session
from app.main import app
from app.models.db import CumulativeUsage


@pytest.fixture
def session():
    """In-memory DB session shared between dependency override and test queries."""
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)

    with Session(engine) as s:
        app.dependency_overrides[get_session] = lambda: s
        yield s
        app.dependency_overrides.pop(get_session, None)


def _hmac_headers(body: str, key: str) -> dict[str, str]:
    timestamp = str(int(time.time()))
    sig = hmac.new(
        key.encode(), f"{timestamp}".encode() + body.encode(), hashlib.sha256
    ).hexdigest()
    return {
        "X-Signature": sig,
        "X-Timestamp": timestamp,
        "Content-Type": "application/json",
    }


def _post_ingest(client: TestClient, payload: dict, key: str):
    body = json.dumps(payload)
    return client.post("/api/v1/fleet/ingest", content=body, headers=_hmac_headers(body, key))


def test_ingest_with_deltas_creates_cumulative_rows(session: Session):
    """A single delta creates lifetime + year + month rows for the same unit_type."""
    test_key = "test-ingest-key-for-deltas"

    payload = {
        "provider": "claude",
        "sidecar_id": "laptop-1",
        "metrics": [],
        "deltas": [
            {
                "provider_id": "anthropic",
                "account_id": "acc1",
                "unit_type": "tokens_input",
                "value": 500.0,
                "timestamp": "2026-05-03T12:00:00Z",
            }
        ],
    }

    with (
        patch("app.api.endpoints.fleet.settings") as mock_settings,
        patch("app.api.endpoints.fleet.token_cache") as mock_tc,
    ):
        mock_settings.INGEST_API_KEY = test_key
        mock_settings.INGEST_API_KEY_IS_INSECURE_DEFAULT = False
        mock_tc.store = AsyncMock()
        client = TestClient(app)
        resp = _post_ingest(client, payload, test_key)

    assert resp.status_code == 200, resp.text

    rows = session.exec(select(CumulativeUsage)).all()
    period_types = sorted(r.period_type for r in rows)
    assert period_types == ["lifetime", "month", "year"]
    for r in rows:
        assert r.provider_id == "anthropic"
        assert r.account_id == "acc1"
        assert r.sidecar_id == "laptop-1"
        assert r.unit_type == "tokens_input"
        assert r.total_value == 500.0


def test_ingest_deltas_accumulate_across_posts(session: Session):
    """Two posts with the same identity sum into the same CumulativeUsage row, not replace it."""
    test_key = "test-ingest-key-for-deltas"

    base = {
        "provider": "claude",
        "sidecar_id": "laptop-1",
        "metrics": [],
        "deltas": [
            {
                "provider_id": "anthropic",
                "account_id": "acc1",
                "unit_type": "tokens_input",
                "value": 100.0,
                "timestamp": "2026-05-03T12:00:00Z",
            }
        ],
    }

    with (
        patch("app.api.endpoints.fleet.settings") as mock_settings,
        patch("app.api.endpoints.fleet.token_cache") as mock_tc,
    ):
        mock_settings.INGEST_API_KEY = test_key
        mock_settings.INGEST_API_KEY_IS_INSECURE_DEFAULT = False
        mock_tc.store = AsyncMock()
        client = TestClient(app)

        r1 = _post_ingest(client, base, test_key)
        assert r1.status_code == 200, r1.text

        # Second post: same identity, +250 tokens, 5 minutes later (still in same month)
        followup = {
            **base,
            "deltas": [
                {
                    **base["deltas"][0],
                    "value": 250.0,
                    "timestamp": "2026-05-03T12:05:00Z",
                }
            ],
        }
        r2 = _post_ingest(client, followup, test_key)
        assert r2.status_code == 200, r2.text

    rows = session.exec(select(CumulativeUsage)).all()
    # Still 3 rows (lifetime/year/month) — accumulation, not duplication
    assert len(rows) == 3
    for r in rows:
        assert r.total_value == 350.0
