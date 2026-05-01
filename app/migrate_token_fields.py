#!/usr/bin/env python3
"""
Schema migration for token fields.

Note: Historical snapshots have empty raw_metadata_json (token data was never
stored there — it lived only in memory on LimitCard objects).  Only NEW
snapshots collected after the poller update will have token columns populated.

This script ensures the schema columns exist.  Data backfill is not possible.

Run: python -m app.migrate_token_fields
"""

import logging
import sys

from sqlalchemy import text

from app.core.db import engine

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger(__name__)

NEW_COLUMNS = [
    ("tokens_input", "FLOAT"),
    ("tokens_output", "FLOAT"),
    ("tokens_reasoning", "FLOAT"),
    ("tokens_cache_read", "FLOAT"),
    ("tokens_total", "FLOAT"),
    ("msgs", "INTEGER"),
]


def migrate_schema():
    """Add missing columns to usage_snapshots and create usage_snapshot_models table."""
    with engine.connect() as conn:
        result = conn.execute(text("PRAGMA table_info(usage_snapshots)"))
        existing_cols = {row[1] for row in result}

        for col_name, col_type in NEW_COLUMNS:
            if col_name not in existing_cols:
                conn.execute(text(f"ALTER TABLE usage_snapshots ADD COLUMN {col_name} {col_type}"))
                logger.info(f"Added column {col_name} to usage_snapshots")
            else:
                logger.info(f"Column {col_name} already exists")

        result = conn.execute(
            text(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='usage_snapshot_models'"
            )
        )
        if not result.fetchone():
            conn.execute(
                text("""
                CREATE TABLE usage_snapshot_models (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id INTEGER NOT NULL,
                    model_id TEXT NOT NULL,
                    cost FLOAT,
                    msgs INTEGER,
                    tokens_input FLOAT,
                    tokens_output FLOAT,
                    tokens_reasoning FLOAT,
                    tokens_cache_read FLOAT,
                    tokens_total FLOAT
                )
            """)
            )
            conn.execute(
                text(
                    "CREATE INDEX ix_snapshot_model_snapshot ON usage_snapshot_models(snapshot_id)"
                )
            )
            logger.info("Created usage_snapshot_models table")
        else:
            logger.info("usage_snapshot_models table already exists")

        conn.commit()
        logger.info("Schema migration complete.")
        logger.info(
            "NOTE: Historical data cannot be backfilled — token data was never stored in "
            "raw_metadata_json. New snapshots will populate these columns automatically."
        )


if __name__ == "__main__":
    try:
        migrate_schema()
    except Exception as e:
        logger.error(f"Migration failed: {e}")
        sys.exit(1)
