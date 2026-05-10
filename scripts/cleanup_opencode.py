from sqlmodel import Session, select, text

from app.core.db import engine
from app.models.db import LatestUsage

PROVIDERS = ("opencode", "opencode-free")
OLD_ID = "default"
NEW_ID = "s3ntin3l8@gmail.com"


def cleanup():
    with Session(engine) as session:
        # ── usage_events ──────────────────────────────────────────────────────
        # Some "default" events were already re-sent under the email account_id
        # by the new sidecar, so a blind UPDATE would violate the unique
        # constraint on (provider_id, account_id, event_id).
        #
        # Strategy:
        #   1. Delete "default" rows whose event_id already exists under email
        #      (true duplicates — the email copy is authoritative).
        #   2. Re-tag the remaining "default" rows (unique to the old account).

        result = session.exec(
            text(
                "DELETE FROM usage_events "
                "WHERE provider_id IN ('opencode', 'opencode-free') "
                "AND account_id = :old "
                "AND event_id IN ("
                "  SELECT event_id FROM usage_events "
                "  WHERE provider_id IN ('opencode', 'opencode-free') "
                "  AND account_id = :new"
                ")"
            ).bindparams(old=OLD_ID, new=NEW_ID)
        )
        dupes_deleted = result.rowcount
        print(f"usage_events: deleted {dupes_deleted} duplicate 'default' rows (already in email)")

        result = session.exec(
            text(
                "UPDATE usage_events SET account_id = :new "
                "WHERE provider_id IN ('opencode', 'opencode-free') "
                "AND account_id = :old"
            ).bindparams(new=NEW_ID, old=OLD_ID)
        )
        retagged = result.rowcount
        print(f"usage_events: re-tagged {retagged} unique 'default' rows → email")

        # ── usage_period_rollup ───────────────────────────────────────────────
        # Rollup rows keyed by (provider_id, account_id, period_type, period_key,
        # model_id, sidecar_id). Conflicts are unlikely but handle the same way.
        result = session.exec(
            text(
                "DELETE FROM usage_period_rollup "
                "WHERE provider_id IN ('opencode', 'opencode-free') "
                "AND account_id = :old "
                "AND (provider_id, period_type, period_key, model_id, sidecar_id) IN ("
                "  SELECT provider_id, period_type, period_key, model_id, sidecar_id "
                "  FROM usage_period_rollup "
                "  WHERE provider_id IN ('opencode', 'opencode-free') "
                "  AND account_id = :new"
                ")"
            ).bindparams(old=OLD_ID, new=NEW_ID)
        )
        print(f"usage_period_rollup: deleted {result.rowcount} duplicate 'default' rows")

        result = session.exec(
            text(
                "UPDATE usage_period_rollup SET account_id = :new "
                "WHERE provider_id IN ('opencode', 'opencode-free') "
                "AND account_id = :old"
            ).bindparams(new=NEW_ID, old=OLD_ID)
        )
        print(f"usage_period_rollup: re-tagged {result.rowcount} unique 'default' rows → email")

        # ── latest_usage ──────────────────────────────────────────────────────
        rows = session.exec(
            select(LatestUsage).where(
                LatestUsage.provider_id.in_(list(PROVIDERS)),
                LatestUsage.account_id == OLD_ID,
            )
        ).all()
        if rows:
            print(f"latest_usage: deleting {len(rows)} 'default' rows...")
            for r in rows:
                session.delete(r)
        else:
            print("latest_usage: no 'default' rows found")

        session.commit()
        print("Done.")


if __name__ == "__main__":
    cleanup()
