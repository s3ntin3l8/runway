#!/usr/bin/env python3
"""One-shot cleanup for a stale ChatGPT/Codex "monthly" gauge card left behind
by a Codex plan upgrade (e.g. Go -> Plus/Pro).

Background
----------
`window_type: "monthly"` is NOT inherently wrong — it is the correct, intended
fallback the collector uses when a Codex window has no `limit_window_seconds`
(Go/free-tier payloads only ever send `rate_limit.primary_window` with no
duration field; see app/services/collectors/chatgpt_web.py). A Go account's
"monthly" row is legitimate and this script must not touch it.

The row becomes stale only when an account's *plan changes* to one that
reports `limit_window_seconds` (Plus/Pro: a 5h `session` window from
`primary_window`, plus a 7d `weekly` window from `secondary_window`). From
that point on the collector emits `session`/`weekly` cards instead, but the
old `monthly` row for that same account is never deleted:
`upsert_latest_usage`'s cross-window_type delete (accumulator.py) is guarded
on `if model_id:`, and ChatGPT cards carry no model_id, so it never fires.
`prune_stale_latest_usage` only runs on a sidecar push, and ChatGPT is
server-collected. So the orphan just sits there next to the new cards
indefinitely.

This script deletes the stale row for ONE named account_id — never a blanket
sweep of every chatgpt/monthly row, since that would also delete a legitimate
Go account's live gauge in a multi-account deployment. latest_usage holds
only live gauges — no event/rollup/history data is lost either way.

Run with the server STOPPED (SQLite is single-writer) and APP_HOST=127.0.0.1,
AFTER deploying the collector fix and AFTER at least one successful poll under
the new plan has produced session/weekly rows for the account (otherwise
you'd be deleting the only card that account has):

  RUNWAY_CONFIG_DIR=~/.config/runway APP_HOST=127.0.0.1 \\
      python scripts/cleanup_chatgpt_monthly_cards.py --account-id <id> --dry-run
  # eyeball the row(s), then:
  RUNWAY_CONFIG_DIR=~/.config/runway APP_HOST=127.0.0.1 \\
      python scripts/cleanup_chatgpt_monthly_cards.py --account-id <id> --apply
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from sqlmodel import Session, delete, select  # noqa: E402

from app.core.db import engine  # noqa: E402
from app.models.db import LatestUsage  # noqa: E402

_PROVIDER = "chatgpt"
_WINDOW_TYPE = "monthly"


def _filters(account_id: str) -> list:
    return [
        LatestUsage.provider_id == _PROVIDER,
        LatestUsage.window_type == _WINDOW_TYPE,
        LatestUsage.account_id == account_id,
    ]


def main() -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument(
        "--account-id",
        required=True,
        help="The account_id that upgraded plans (see latest_usage.account_id). "
        "Scoping is deliberate — a Go/free account's monthly row is correct and "
        "must not be swept up alongside a switched account's stale one.",
    )
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument(
        "--dry-run", action="store_true", help="Report what would be deleted without writing."
    )
    g.add_argument("--apply", action="store_true", help="Delete the stale row(s).")
    args = p.parse_args()
    dry_run = args.dry_run
    prefix = "[DRY-RUN] " if dry_run else ""

    with Session(engine) as session:
        rows = session.exec(select(LatestUsage).where(*_filters(args.account_id))).all()
        verb = "Would delete" if dry_run else "Deleting"
        print(
            f"{prefix}{verb} {len(rows)} latest_usage row(s) "
            f"({_PROVIDER}/{_WINDOW_TYPE}/{args.account_id!r}):",
            flush=True,
        )
        for r in rows:
            print(
                f"  id={r.id} account_id={r.account_id!r} "
                f"model_id={r.model_id!r} updated_at={r.updated_at}",
                flush=True,
            )

        if not dry_run and rows:
            session.exec(delete(LatestUsage).where(*_filters(args.account_id)))
            session.commit()
            print(f"Deleted {len(rows)} row(s).", flush=True)

    return 0


if __name__ == "__main__":
    sys.exit(main())
