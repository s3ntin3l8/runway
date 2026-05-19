"""Auto-extracted from app.services.event_query during the monolith split.
See app/services/queries/__init__.py for the public surface.
"""

import calendar
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, select

from app.models.db import UsagePeriodRollup
from app.services.queries._shared import _parse_ts  # noqa: F401


def query_hourly_token_buckets_batch(
    session: Session,
    *,
    since: datetime,
    until: datetime,
) -> dict[tuple[str, str], list[tuple[datetime, str, int]]]:
    """All hourly token buckets in [since, until], partitioned by (provider, account).

    Single scan, then Python-side partitioning. Replaces per-card N+1 queries
    from `_fetch_hourly_buckets` when many cards share an overlapping window.
    Token sum excludes tokens_reasoning (already a sub-type of output).
    model_id is returned as an empty string when null in the source row.
    """

    def _naive_utc_str(dt: datetime) -> str:
        return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")

    sql = text(
        """
        SELECT
            provider_id,
            account_id,
            strftime('%Y-%m-%d %H:00:00', ts) AS hour_bucket,
            COALESCE(model_id, '') AS model_id,
            SUM(tokens_input + tokens_output + tokens_cache_read
                 + tokens_cache_create) AS toks
        FROM usage_events
        WHERE ts >= :since AND ts <= :until
        GROUP BY provider_id, account_id, hour_bucket, COALESCE(model_id, '')
        ORDER BY hour_bucket ASC
        """
    )
    rows = session.exec(  # type: ignore[call-overload]
        sql,
        params={
            "since": _naive_utc_str(since),
            "until": _naive_utc_str(until),
        },
    ).all()

    result: dict[tuple[str, str], list[tuple[datetime, str, int]]] = {}
    for row in rows:
        key = (str(row.provider_id), str(row.account_id))
        try:
            ts = datetime.strptime(str(row.hour_bucket), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            continue
        result.setdefault(key, []).append((ts, str(row.model_id), int(row.toks or 0)))
    return result


def query_cost_hourly(
    session: Session,
    *,
    provider_id: str,
    account_id: str,
    since: datetime,
    until: datetime,
) -> list[tuple[datetime, float, int]]:
    """Hourly (ts, cost_sum, tokens_sum) buckets from usage_events.

    For short forecast windows (session/daily) the day-grain rollup table
    yields too few buckets for a trend. This goes straight to the event log
    and bucket-sums on the fly.

    SQLite stores naive UTC strings; passing ISO-8601 'T'-separated with
    timezone breaks string comparisons. Same naive-UTC formatting as
    _fetch_hourly_buckets.
    """

    def _naive_utc_str(dt: datetime) -> str:
        return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")

    sql = text(
        """
        SELECT
            strftime('%Y-%m-%d %H:00:00', ts) AS hour_bucket,
            SUM(cost_usd) AS cost,
            SUM(tokens_input + tokens_output + tokens_cache_read
                + tokens_cache_create) AS toks
        FROM usage_events
        WHERE provider_id = :provider_id
          AND account_id  = :account_id
          AND ts >= :since
          AND ts <= :until
        GROUP BY hour_bucket
        ORDER BY hour_bucket ASC
        """
    )
    rows = session.exec(  # type: ignore[call-overload]
        sql,
        params={
            "provider_id": provider_id,
            "account_id": account_id,
            "since": _naive_utc_str(since),
            "until": _naive_utc_str(until),
        },
    ).all()

    result: list[tuple[datetime, float, int]] = []
    for row in rows:
        try:
            ts = datetime.strptime(str(row.hour_bucket), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            continue
        result.append((ts, float(row.cost or 0), int(row.toks or 0)))
    return result


def query_cost_buckets(
    session: Session,
    *,
    provider_id: str,
    account_id: str,
    since_key: str,
    until_key: str,
) -> list[tuple[str, float, int]]:
    """Daily (cost_usd, token total) buckets for one (provider, account) pair.

    Returns rows of (period_key, daily_cost, daily_tokens) inclusive of both
    boundary keys, ordered oldest-first. period_key format is "YYYY-MM-DD"
    (the natural index on the rollup table).
    """
    sql = text(
        """
        SELECT
            period_key,
            SUM(cost_usd) AS daily_cost,
            SUM(tokens_input + tokens_output + tokens_cache_read
                 + tokens_cache_create + tokens_reasoning) AS daily_tokens
        FROM usage_period_rollup
        WHERE period_type = 'day'
          AND model_id = ''
          AND sidecar_id = ''
          AND period_key >= :since_key
          AND period_key <= :until_key
          AND provider_id = :provider_id
          AND account_id = :account_id
        GROUP BY period_key
        ORDER BY period_key ASC
        """
    )
    rows = session.exec(  # type: ignore[call-overload]
        sql,
        params={
            "since_key": since_key,
            "until_key": until_key,
            "provider_id": provider_id,
            "account_id": account_id,
        },
    ).all()
    return [(str(r.period_key), float(r.daily_cost or 0), int(r.daily_tokens or 0)) for r in rows]


def query_cost_forecast(
    session: Session,
    *,
    provider_id: str | None = None,
    account_id: str | None = None,
) -> dict[str, Any]:
    """Return a cost forecast combining current MTD with 7-day burn average.

    Algorithm:
    - MTD: sum cost_usd from period_type=month, model_id='', sidecar_id='' for current month.
    - 7d avg: sum cost_usd from period_type=day, model_id='', sidecar_id='' for past 7 days
              divided by 7 (always divides by 7, zero-filling missing days).
    - projected_eom = MTD + (daily_avg × days_remaining).
    """
    now = datetime.now(UTC)
    days_in_month = calendar.monthrange(now.year, now.month)[1]
    day_of_month = now.day
    days_remaining = days_in_month - day_of_month
    month_key = now.strftime("%Y-%m")
    seven_days_ago = (now - timedelta(days=7)).strftime("%Y-%m-%d")

    # Fetch current-month rollup rows (all-up grain: model_id='', sidecar_id='')
    mtd_stmt = select(UsagePeriodRollup).where(
        UsagePeriodRollup.period_type == "month",
        UsagePeriodRollup.period_key == month_key,
        UsagePeriodRollup.model_id == "",
        UsagePeriodRollup.sidecar_id == "",
    )
    if provider_id:
        mtd_stmt = mtd_stmt.where(UsagePeriodRollup.provider_id == provider_id)
    if account_id:
        mtd_stmt = mtd_stmt.where(UsagePeriodRollup.account_id == account_id)
    mtd_rows = list(session.exec(mtd_stmt).all())

    # Fetch last-7-days daily rollup rows (all-up grain)
    daily_stmt = select(UsagePeriodRollup).where(
        UsagePeriodRollup.period_type == "day",
        UsagePeriodRollup.model_id == "",
        UsagePeriodRollup.sidecar_id == "",
        UsagePeriodRollup.period_key >= seven_days_ago,
    )
    if provider_id:
        daily_stmt = daily_stmt.where(UsagePeriodRollup.provider_id == provider_id)
    if account_id:
        daily_stmt = daily_stmt.where(UsagePeriodRollup.account_id == account_id)
    daily_rows = list(session.exec(daily_stmt).all())

    # Group by (provider_id, account_id)
    AccountKey = tuple[str, str]
    mtd_by_account: dict[AccountKey, float] = {}
    for r in mtd_rows:
        key: AccountKey = (r.provider_id, r.account_id)
        mtd_by_account[key] = mtd_by_account.get(key, 0.0) + r.cost_usd

    daily_sum_by_account: dict[AccountKey, float] = {}
    for r in daily_rows:
        key = (r.provider_id, r.account_id)
        daily_sum_by_account[key] = daily_sum_by_account.get(key, 0.0) + r.cost_usd

    # Build per-account breakdown
    all_keys: set[AccountKey] = set(mtd_by_account.keys()) | set(daily_sum_by_account.keys())
    by_provider: list[dict[str, Any]] = []
    total_mtd = 0.0
    total_7d_sum = 0.0

    for key in sorted(all_keys):
        pid, aid = key
        mtd = mtd_by_account.get(key, 0.0)
        seven_d_sum = daily_sum_by_account.get(key, 0.0)
        daily_avg = seven_d_sum / 7.0
        projected = mtd + daily_avg * days_remaining if daily_avg > 0 else mtd
        by_provider.append(
            {
                "provider_id": pid,
                "account_id": aid,
                "current_month_to_date": round(mtd, 6),
                "daily_burn_avg_7d": round(daily_avg, 6),
                "projected_eom": round(projected, 6),
            }
        )
        total_mtd += mtd
        total_7d_sum += seven_d_sum

    total_daily_avg = total_7d_sum / 7.0
    total_projected = (
        total_mtd + total_daily_avg * days_remaining if total_daily_avg > 0 else total_mtd
    )

    return {
        "as_of": now.isoformat(),
        "current_month_to_date": round(total_mtd, 6),
        "daily_burn_avg_7d": round(total_daily_avg, 6),
        "projected_eom": round(total_projected, 6),
        "days_in_month": days_in_month,
        "day_of_month": day_of_month,
        "days_remaining": days_remaining,
        "by_provider": by_provider,
    }


# ---------------------------------------------------------------------------
# 14.3  query_anomalies
# ---------------------------------------------------------------------------
