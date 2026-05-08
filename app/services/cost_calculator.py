"""Compute cost_usd for a usage event using provider_pricing."""

from datetime import datetime

from sqlmodel import Session, select

from app.models.db import ProviderPricing


def compute_event_cost(
    session: Session,
    *,
    provider_id: str,
    model_id: str | None,
    ts: datetime,
    tokens_input: int,
    tokens_output: int,
    tokens_cache_read: int,
    tokens_cache_create: int,
    tokens_reasoning: int = 0,
) -> float:
    """Return USD cost for an event using the price row in effect at `ts`.

    Returns 0.0 when no pricing row matches. Reasoning tokens are billed at
    the output rate (Anthropic / OpenAI convention)."""
    if not model_id:
        return 0.0
    row = session.exec(
        select(ProviderPricing)
        .where(
            ProviderPricing.provider_id == provider_id,
            ProviderPricing.model_id == model_id,
            ProviderPricing.effective_from <= ts.date(),
        )
        .order_by(ProviderPricing.effective_from.desc())
    ).first()
    if not row:
        return 0.0
    return round(
        tokens_input / 1_000_000 * row.input_per_mtok
        + (tokens_output + tokens_reasoning) / 1_000_000 * row.output_per_mtok
        + tokens_cache_read / 1_000_000 * row.cache_read_per_mtok
        + tokens_cache_create / 1_000_000 * row.cache_create_per_mtok,
        6,
    )
