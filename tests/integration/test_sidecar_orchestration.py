import json
import time

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.core.db import get_session
from app.main import app
from app.models.db import LatestUsage, ProviderConfig
from app.services.accumulator import merge_card_json
from app.services.fleet_registry import fleet_registry


@pytest.fixture(name="session")
def session_fixture():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


@pytest.fixture(name="client")
def client_fixture(session):
    def get_session_override():
        return session

    app.dependency_overrides[get_session] = get_session_override
    client = TestClient(app)
    # Clear in-memory history before each test
    fleet_registry._last_provider_polls.clear()
    fleet_registry._pending_triggers.clear()
    yield client
    app.dependency_overrides.clear()


def test_ingest_heartbeat_returns_poll_providers(client, session):
    # 1. Setup providers and intervals
    session.add(ProviderConfig(provider_id="anthropic", enabled=True, poll_interval_seconds=300))
    session.add(ProviderConfig(provider_id="github", enabled=True, poll_interval_seconds=600))
    session.commit()

    # Set secret key to avoid 503
    from app.core.config import settings

    settings.INGEST_API_KEY = "test-key"

    def get_signed_payload(payload: dict, key: str):
        import hashlib
        import hmac
        import json

        ts = str(time.time())
        body_bytes = json.dumps(payload, separators=(",", ":")).encode()
        sig = hmac.new(key.encode(), ts.encode() + body_bytes, hashlib.sha256).hexdigest()
        return body_bytes, {"X-Signature": sig, "X-Timestamp": ts}

    payload = {
        "provider": "sidecar-test",
        "sidecar_id": "test-sidecar",
        "metrics": [],
        "deltas": [],
    }

    body, headers = get_signed_payload(payload, "test-key")

    # 2. First heartbeat: should trigger both
    resp = client.post("/api/v1/fleet/ingest", content=body, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert set(data["poll_providers"]) == {"anthropic", "github"}

    # 3. Second heartbeat (immediate): should trigger NONE
    body, headers = get_signed_payload(payload, "test-key")
    resp = client.post("/api/v1/fleet/ingest", content=body, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["poll_providers"] == []

    # 4. Mock time passage (force one to be due)
    fleet_registry._last_provider_polls["test-sidecar"]["anthropic"] = time.time() - 400

    body, headers = get_signed_payload(payload, "test-key")
    resp = client.post("/api/v1/fleet/ingest", content=body, headers=headers)
    assert resp.status_code == 200
    assert resp.json()["poll_providers"] == ["anthropic"]

    # 5. Manual Trigger: should return ALL enabled providers and trigger=True
    resp = client.post(
        "/api/v1/fleet/sidecars/test-sidecar/trigger", headers={"X-API-Key": "test-key"}
    )
    assert resp.status_code == 200

    body, headers = get_signed_payload(payload, "test-key")
    resp = client.post("/api/v1/fleet/ingest", content=body, headers=headers)
    assert resp.status_code == 200
    data = resp.json()
    assert set(data["poll_providers"]) == {"anthropic", "github"}
    assert data["trigger"] is True


def test_server_and_sidecar_cards_merge_into_one_latest_usage_row(session):
    """Server scrape and sidecar enrichment must land in a single LatestUsage row."""
    # 1. Simulate a server scrape writing the initial row
    server_card_json = json.dumps(
        {
            "pct_used": 12.0,
            "limit_value": 100.0,
            "token_usage": None,
            "data_source": "web",
            "input_source": "server",
        }
    )
    server_row = LatestUsage(
        provider_id="anthropic",
        account_id="s3ntin3l8@gmail.com",
        sidecar_id="local",
        window_type="weekly",
        variant="default",
        model_id="",
        card_json=server_card_json,
    )
    session.add(server_row)
    session.commit()

    # 2. Simulate sidecar enrichment: look up by identity tuple (no sidecar_id),
    #    then merge incoming fields into the existing row
    sidecar_card = {
        "token_usage": {"total": 654000000},
        "by_model": {"sonnet": {"tokens": 100}},
        "data_source": "local",
        "input_source": "unknown",
    }

    existing = session.exec(
        select(LatestUsage).where(
            LatestUsage.provider_id == "anthropic",
            LatestUsage.account_id == "s3ntin3l8@gmail.com",
            LatestUsage.window_type == "weekly",
            LatestUsage.variant == "default",
            LatestUsage.model_id == "",
        )
    ).first()

    assert existing is not None, "Server-scrape row must exist before sidecar merge"
    existing.card_json = merge_card_json(existing.card_json, sidecar_card)
    existing.sidecar_id = "dev-01"
    session.commit()

    # 3. Assert exactly one row and merged fields
    all_rows = session.exec(
        select(LatestUsage).where(
            LatestUsage.provider_id == "anthropic",
            LatestUsage.account_id == "s3ntin3l8@gmail.com",
        )
    ).all()
    assert len(all_rows) == 1, f"Expected 1 row, got {len(all_rows)}"

    merged = json.loads(all_rows[0].card_json)
    assert merged["pct_used"] == 12.0, "pct_used from server scrape must be preserved"
    assert merged["token_usage"]["total"] == 654000000, "token_usage from sidecar must be present"
    assert "web" in merged["data_source"], "web data_source must be preserved"
    assert "local" in merged["data_source"], "local data_source from sidecar must be merged"
