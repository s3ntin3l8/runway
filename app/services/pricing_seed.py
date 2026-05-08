"""Seed provider_pricing with current public rates.

Add new rows (don't modify existing) when prices change — the
effective_from column is the natural version key.
"""

from datetime import date

from sqlmodel import Session, select

from app.models.db import ProviderPricing

PRICING_SEED: list[dict] = [
    # Anthropic Claude (Sonnet 4.5, Opus 4.5, Haiku 4.5)
    {
        "provider_id": "anthropic",
        "model_id": "sonnet",
        "effective_from": "2025-09-01",
        "input_per_mtok": 3.00,
        "output_per_mtok": 15.00,
        "cache_read_per_mtok": 0.30,
        "cache_create_per_mtok": 3.75,
        "notes": "Sonnet 4.5",
    },
    {
        "provider_id": "anthropic",
        "model_id": "opus",
        "effective_from": "2025-09-01",
        "input_per_mtok": 15.00,
        "output_per_mtok": 75.00,
        "cache_read_per_mtok": 1.50,
        "cache_create_per_mtok": 18.75,
        "notes": "Opus 4.5",
    },
    {
        "provider_id": "anthropic",
        "model_id": "haiku",
        "effective_from": "2025-09-01",
        "input_per_mtok": 0.80,
        "output_per_mtok": 4.00,
        "cache_read_per_mtok": 0.08,
        "cache_create_per_mtok": 1.00,
        "notes": "Haiku 4.5",
    },
    # OpenAI ChatGPT / Codex (GPT-5 series)
    {
        "provider_id": "chatgpt",
        "model_id": "gpt-5",
        "effective_from": "2025-08-01",
        "input_per_mtok": 5.00,
        "output_per_mtok": 15.00,
        "cache_read_per_mtok": 1.25,
        "cache_create_per_mtok": 0.0,
        "notes": "GPT-5 standard",
    },
    {
        "provider_id": "chatgpt",
        "model_id": "codex",
        "effective_from": "2025-08-01",
        "input_per_mtok": 5.00,
        "output_per_mtok": 15.00,
        "cache_read_per_mtok": 1.25,
        "cache_create_per_mtok": 0.0,
        "notes": "GPT-5 Codex (Plus tier)",
    },
    # Google Gemini
    {
        "provider_id": "gemini",
        "model_id": "pro",
        "effective_from": "2025-09-01",
        "input_per_mtok": 1.25,
        "output_per_mtok": 10.00,
        "cache_read_per_mtok": 0.31,
        "cache_create_per_mtok": 0.0,
        "notes": "Gemini 2.5 Pro",
    },
    {
        "provider_id": "gemini",
        "model_id": "flash",
        "effective_from": "2025-09-01",
        "input_per_mtok": 0.30,
        "output_per_mtok": 2.50,
        "cache_read_per_mtok": 0.075,
        "cache_create_per_mtok": 0.0,
        "notes": "Gemini 2.5 Flash",
    },
    {
        "provider_id": "gemini",
        "model_id": "flash-lite",
        "effective_from": "2025-09-01",
        "input_per_mtok": 0.10,
        "output_per_mtok": 0.40,
        "cache_read_per_mtok": 0.025,
        "cache_create_per_mtok": 0.0,
        "notes": "Gemini 2.5 Flash Lite",
    },
    # OpenCode (cost is on each event already; pricing rows here are fallback only)
]


def seed_pricing_table(session: Session) -> int:
    """Insert any seed rows missing from provider_pricing. Returns rows inserted."""
    inserted = 0
    for row in PRICING_SEED:
        exists = session.exec(
            select(ProviderPricing).where(
                ProviderPricing.provider_id == row["provider_id"],
                ProviderPricing.model_id == row["model_id"],
                ProviderPricing.effective_from == date.fromisoformat(row["effective_from"]),
            )
        ).first()
        if exists:
            continue
        session.add(
            ProviderPricing(
                provider_id=row["provider_id"],
                model_id=row["model_id"],
                effective_from=date.fromisoformat(row["effective_from"]),
                input_per_mtok=row["input_per_mtok"],
                output_per_mtok=row["output_per_mtok"],
                cache_read_per_mtok=row["cache_read_per_mtok"],
                cache_create_per_mtok=row["cache_create_per_mtok"],
                notes=row.get("notes"),
            )
        )
        inserted += 1
    session.commit()
    return inserted
