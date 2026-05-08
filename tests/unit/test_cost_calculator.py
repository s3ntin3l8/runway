from datetime import UTC, datetime

from sqlmodel import Session, SQLModel, create_engine
from sqlmodel.pool import StaticPool

from app.services.cost_calculator import compute_event_cost
from app.services.pricing_seed import seed_pricing_table


def _seeded_session():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    SQLModel.metadata.create_all(engine)
    s = Session(engine)
    seed_pricing_table(s)
    return s


def test_anthropic_sonnet_cost_basic_input_output():
    """1M input + 1M output on sonnet = $3 + $15 = $18."""
    s = _seeded_session()
    cost = compute_event_cost(
        s,
        provider_id="anthropic",
        model_id="sonnet",
        ts=datetime.now(UTC),
        tokens_input=1_000_000,
        tokens_output=1_000_000,
        tokens_cache_read=0,
        tokens_cache_create=0,
        tokens_reasoning=0,
    )
    assert cost == 18.00


def test_anthropic_sonnet_cost_includes_cache():
    """cache_read at $0.30/MT, cache_create at $3.75/MT."""
    s = _seeded_session()
    cost = compute_event_cost(
        s,
        provider_id="anthropic",
        model_id="sonnet",
        ts=datetime.now(UTC),
        tokens_input=1_000_000,
        tokens_output=1_000_000,
        tokens_cache_read=1_000_000,
        tokens_cache_create=1_000_000,
        tokens_reasoning=0,
    )
    assert cost == 18.00 + 0.30 + 3.75


def test_unknown_model_returns_zero():
    s = _seeded_session()
    cost = compute_event_cost(
        s,
        provider_id="anthropic",
        model_id="<unknown>",
        ts=datetime.now(UTC),
        tokens_input=1_000_000,
        tokens_output=1_000_000,
        tokens_cache_read=0,
        tokens_cache_create=0,
        tokens_reasoning=0,
    )
    assert cost == 0.0
