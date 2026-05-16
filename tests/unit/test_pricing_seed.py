from sqlmodel import Session, SQLModel, create_engine, select
from sqlmodel.pool import StaticPool

from app.models.db import ProviderPricing
from app.services.pricing_seed import PRICING_SEED, seed_pricing_table


def _make_session():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SQLModel.metadata.create_all(engine)
    return Session(engine)


def test_seed_inserts_all_rows_on_empty_db():
    s = _make_session()
    seed_pricing_table(s)
    rows = s.exec(select(ProviderPricing)).all()
    assert len(rows) == len(PRICING_SEED)


def test_seed_is_idempotent():
    s = _make_session()
    seed_pricing_table(s)
    seed_pricing_table(s)  # second call should be a no-op
    rows = s.exec(select(ProviderPricing)).all()
    assert len(rows) == len(PRICING_SEED)


def test_seed_chatgpt_gpt54_mini_rates():
    s = _make_session()
    seed_pricing_table(s)
    row = s.exec(
        select(ProviderPricing).where(
            ProviderPricing.provider_id == "chatgpt",
            ProviderPricing.model_id == "gpt-5.4-mini",
        )
    ).first()
    assert row is not None
    assert row.input_per_mtok == 0.75
    assert row.output_per_mtok == 4.50
    assert row.cache_read_per_mtok == 0.075
    assert row.cache_create_per_mtok == 0.0


def test_seed_preserves_anthropic_sonnet_rates():
    s = _make_session()
    seed_pricing_table(s)
    sonnet = s.exec(
        select(ProviderPricing).where(
            ProviderPricing.provider_id == "anthropic",
            ProviderPricing.model_id == "sonnet",
        )
    ).first()
    assert sonnet is not None
    assert sonnet.input_per_mtok == 3.00
    assert sonnet.output_per_mtok == 15.00
    assert sonnet.cache_read_per_mtok == 0.30
    assert sonnet.cache_create_per_mtok == 3.75
