"""Integration tests: GET /api/v1/usage/fleet — Fleet Commander aggregation.

Rewritten in Phase 9 to use LatestUsage + UsagePeriodRollup instead of
the deleted CumulativeUsage table.
"""

import json
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.core.db import get_session
from app.main import app
from app.models.db import LatestUsage, UsagePeriodRollup

# ---------------------------------------------------------------------------
# Fixture
# ---------------------------------------------------------------------------


@pytest.fixture
def session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    with Session(engine) as s:
        app.dependency_overrides[get_session] = lambda: s
        yield s
        app.dependency_overrides.pop(get_session, None)


def _client():
    return TestClient(app)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _seed_card(
    session: Session,
    *,
    provider_id: str,
    account_id: str,
    window_type: str = "monthly",
    variant: str = "default",
    model_id: str = "",
    pct_used: float | None = None,
    service_name: str | None = None,
) -> None:
    card = {
        "service_name": service_name or f"{provider_id}-{window_type}",
        "provider_id": provider_id,
        "account_id": account_id,
        "window_type": window_type,
        "variant": variant,
        "pct_used": pct_used,
    }
    session.add(
        LatestUsage(
            provider_id=provider_id,
            account_id=account_id,
            sidecar_id="local",
            window_type=window_type,
            variant=variant,
            model_id=model_id,
            card_json=json.dumps(card),
        )
    )


def _seed_rollup(
    session: Session,
    *,
    provider_id: str = "anthropic",
    account_id: str = "u@x.com",
    period_type: str = "month",
    period_key: str | None = None,
    model_id: str = "",
    sidecar_id: str = "",
    tokens_input: int = 0,
    tokens_output: int = 0,
    tokens_cache_read: int = 0,
    tokens_cache_create: int = 0,
    tokens_reasoning: int = 0,
    cost_usd: float = 0.0,
    msgs: int = 0,
) -> UsagePeriodRollup:
    if period_key is None:
        period_key = datetime.now(UTC).strftime("%Y-%m") if period_type == "month" else "all"
    row = UsagePeriodRollup(
        provider_id=provider_id,
        account_id=account_id,
        period_type=period_type,
        period_key=period_key,
        model_id=model_id,
        sidecar_id=sidecar_id,
        tokens_input=tokens_input,
        tokens_output=tokens_output,
        tokens_cache_read=tokens_cache_read,
        tokens_cache_create=tokens_cache_create,
        tokens_reasoning=tokens_reasoning,
        cost_usd=cost_usd,
        msgs=msgs,
        last_updated=datetime.now(UTC),
    )
    session.add(row)
    session.commit()
    return row


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_fleet_returns_critical_gauge_per_account(session: Session):
    """When an account has multiple cards, the highest pct_used becomes critical_gauge."""
    _seed_card(
        session, provider_id="anthropic", account_id="acc1", window_type="weekly", pct_used=30.0
    )
    _seed_card(
        session, provider_id="anthropic", account_id="acc1", window_type="monthly", pct_used=85.0
    )
    session.commit()

    resp = _client().get("/api/v1/usage/fleet")
    assert resp.status_code == 200, resp.text

    fleet = resp.json()["fleet"]
    assert len(fleet) == 1
    entry = fleet[0]
    assert entry["provider_id"] == "anthropic"
    assert entry["account_id"] == "acc1"
    assert entry["critical_gauge"]["pct_used"] == 85.0
    assert len(entry["secondary_limits"]) == 1
    assert entry["secondary_limits"][0]["pct_used"] == 30.0


def test_fleet_groups_by_provider_account(session: Session):
    """Each (provider_id, account_id) gets its own Fleet Commander entry."""
    _seed_card(session, provider_id="anthropic", account_id="acc1", pct_used=50.0)
    _seed_card(session, provider_id="chatgpt", account_id="acc1", pct_used=20.0)
    session.commit()

    resp = _client().get("/api/v1/usage/fleet")
    assert resp.status_code == 200

    fleet = resp.json()["fleet"]
    assert len(fleet) == 2
    pids = {e["provider_id"] for e in fleet}
    assert pids == {"anthropic", "chatgpt"}


def test_fleet_includes_sidecar_contributions(session: Session):
    """Per-sidecar rollup rows for the current month appear in sidecar_contributions."""
    _seed_card(session, provider_id="anthropic", account_id="u@x.com", pct_used=10.0)
    session.commit()

    month_key = datetime.now(UTC).strftime("%Y-%m")
    _seed_rollup(
        session,
        provider_id="anthropic",
        account_id="u@x.com",
        period_type="month",
        period_key=month_key,
        model_id="",
        sidecar_id="laptop-1",
        tokens_input=9234,
        tokens_output=1500,
        cost_usd=0.42,
        msgs=7,
    )

    resp = _client().get("/api/v1/usage/fleet")
    assert resp.status_code == 200

    entry = resp.json()["fleet"][0]
    contrib = entry["sidecar_contributions"]
    assert "laptop-1" in contrib
    assert contrib["laptop-1"]["tokens_input"] == 9234
    assert contrib["laptop-1"]["tokens_output"] == 1500
    assert contrib["laptop-1"]["cost_usd"] == pytest.approx(0.42)
    assert contrib["laptop-1"]["msgs"] == 7


def test_fleet_excludes_other_periods(session: Session):
    """Only current-month rollup rows appear in contributions; lifetime rows are excluded."""
    _seed_card(session, provider_id="anthropic", account_id="u@x.com", pct_used=10.0)
    session.commit()

    month_key = datetime.now(UTC).strftime("%Y-%m")

    # Current-month per-sidecar row — should appear
    _seed_rollup(
        session,
        period_type="month",
        period_key=month_key,
        sidecar_id="laptop-1",
        tokens_input=100,
    )

    # Lifetime per-sidecar row — should NOT appear
    _seed_rollup(
        session,
        period_type="lifetime",
        period_key="all",
        sidecar_id="laptop-1",
        tokens_input=999999,
    )

    resp = _client().get("/api/v1/usage/fleet")
    assert resp.status_code == 200

    contrib = resp.json()["fleet"][0]["sidecar_contributions"]
    # laptop-1 is present, but its value comes only from the current-month row
    assert "laptop-1" in contrib
    assert contrib["laptop-1"]["tokens_input"] == 100


def test_fleet_skips_cross_product_rollup(session: Session):
    """Cross-product rows (model_id != '' AND sidecar_id != '') are excluded.

    Only pure per-sidecar rows (model_id='', sidecar_id!='') should appear.
    """
    _seed_card(session, provider_id="anthropic", account_id="u@x.com", pct_used=10.0)
    session.commit()

    month_key = datetime.now(UTC).strftime("%Y-%m")

    # Pure per-sidecar row (model_id='', sidecar_id set) — should appear
    _seed_rollup(
        session,
        period_type="month",
        period_key=month_key,
        model_id="",
        sidecar_id="laptop-1",
        tokens_input=500,
    )

    # Cross-product row (model_id AND sidecar_id both set) — must NOT appear
    _seed_rollup(
        session,
        period_type="month",
        period_key=month_key,
        model_id="claude-sonnet",
        sidecar_id="laptop-1",
        tokens_input=9999,
    )

    resp = _client().get("/api/v1/usage/fleet")
    assert resp.status_code == 200

    contrib = resp.json()["fleet"][0]["sidecar_contributions"]
    assert "laptop-1" in contrib
    # tokens_input must be from the per-sidecar row (500), not the cross-product (9999)
    assert contrib["laptop-1"]["tokens_input"] == 500


def test_empty_db_returns_empty_fleet(session: Session):
    """No LatestUsage rows → fleet array is empty."""
    resp = _client().get("/api/v1/usage/fleet")
    assert resp.status_code == 200
    body = resp.json()
    assert body["fleet"] == []
    assert "generated_at" in body
