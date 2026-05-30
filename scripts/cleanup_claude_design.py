"""One-shot: remove stale Claude Design / Cowork quota cards from latest_usage.

Claude Design switched from its own dedicated quota to a shared quota, so the
Anthropic API now returns `seven_day_omelette` / `seven_day_cowork` as null and
the collectors no longer emit those cards. The previously-persisted rows linger
in `latest_usage` because the upsert path never deletes a row the collector
stopped reporting, and the auto-pruner only touches rows whose window has already
closed (these carry no reset_at). This script deletes them.

Scoped to `latest_usage` only — historical tables (usage_period_rollup,
usage_windows, quota_snapshots) keep their model_id='design' rows intact.

Idempotent: re-running finds 0 rows. Run from the repo root:
    python -m scripts.cleanup_claude_design
"""

from sqlmodel import Session, select

from app.core.db import engine
from app.models.db import LatestUsage

PROVIDER = "anthropic"
DEAD_MODEL_IDS = ("design", "cowork")


def cleanup():
    with Session(engine) as session:
        rows = session.exec(
            select(LatestUsage).where(
                LatestUsage.provider_id == PROVIDER,
                LatestUsage.model_id.in_(list(DEAD_MODEL_IDS)),
            )
        ).all()
        if rows:
            print(f"latest_usage: deleting {len(rows)} Claude Design/Cowork row(s)...")
            for r in rows:
                print(f"  - {r.account_id} | {r.window_type} | model_id={r.model_id}")
                session.delete(r)
        else:
            print("latest_usage: no Claude Design/Cowork rows found")

        session.commit()
        print("Done.")


if __name__ == "__main__":
    cleanup()
