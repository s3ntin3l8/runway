"""Quota usage forecast service — event-sourced implementation.

Algorithm per card with unit_type='tokens' and limit_value > 0:
1. Compute window_start = reset_at - WINDOW_DURATIONS[window_type]
2. Query usage_events, group into hourly buckets, build cumulative token series
3. Convert (ts, cumulative_tokens) → (elapsed_seconds, pct_used) via limit_value
4. Run linear_regression(elapsed_seconds, pct_used) → slope + intercept
5. Project to reset_seconds → projected_pct_at_reset

Non-token-denominated unit types (percent, currency) are not supported here;
they return None. This is intentional: dividing raw token event sums by a
non-token limit_value (e.g. 100 for a %-based card) produces nonsense.
Forecasting for those card types is deferred to a future phase.
"""

import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from statistics import median

from sqlalchemy import text
from sqlmodel import Session

from app.models.schemas import ForecastEntry, ForecastResponse, LimitCard

logger = logging.getLogger(__name__)

WINDOW_DURATIONS: dict[str, timedelta] = {
    "session": timedelta(hours=5),
    "daily": timedelta(hours=24),
    "weekly": timedelta(days=7),
    "biweekly": timedelta(days=14),
    "monthly": timedelta(days=30),
    "rolling": timedelta(days=30),
}

# Minimum number of distinct buckets before we trust a slope. Below this we
# return insufficient_data; otherwise a single recent spike skews the fit.
MIN_BUCKETS_FOR_TREND = 4

# A projection within this many percentage points of now_pct is reported as
# "stable" rather than a real forecast. Covers rounded-series noise and
# downward-clamped slopes where the "forecast" would just echo the current value.
STABLE_PCT_EPSILON = 0.1

# Status thresholds in pct_used terms.
LIMIT_PCT = 100.0
EXHAUSTED_PCT = 99.9
WARN_PCT = 80.0
# Phase 2 — projected_limit_hit_at is suppressed if the predicted hit time lies
# more than this many window-durations in the future.
HORIZON_CAP_MULTIPLIER = 2.0
# Phase 2 — status "decelerating" applies only above this current-usage floor.
DECELERATING_NOW_PCT_THRESHOLD = WARN_PCT


@dataclass(frozen=True)
class TrendFit:
    """A linear fit (slope, intercept) tagged with the method used to compute it.

    Phase 2 swaps the underlying estimator from OLS linear_regression to Theil-Sen,
    in which case `method` switches from "linear" to "theil_sen".
    """

    slope: float
    intercept: float
    method: str  # "linear" | "theil_sen"


@dataclass(frozen=True)
class _NowState:
    """Card's current position (kept as a bundle so it travels as one arg)."""

    used: float | None
    pct: float | None


@dataclass(frozen=True)
class _SeriesData:
    """Per-bucket cumulative-pct trajectory used to fit a trend.

    `xs` is elapsed seconds from window_start; `ys` is cumulative pct.
    """

    xs: list[float]
    ys: list[float]


@dataclass(frozen=True)
class _Projection:
    """Projected position at the end of the window."""

    used: float | None = None
    pct: float | None = None
    hit_at: str | None = None


def _fit_trend(xs: list[float], ys: list[float]) -> TrendFit | None:
    """Fit a linear trend using Theil-Sen estimator (median of pairwise slopes).

    Resistant to outliers: a single spike in one bucket can't drag the slope
    the way OLS can. Intercept uses Theil-Sen's conventional `median(y_i - slope * x_i)`
    so the line `(LIMIT_PCT - intercept) / slope` for hit_at is consistent with
    the slope estimate.

    Returns None below MIN_BUCKETS_FOR_TREND points.
    """
    n = len(xs)
    if n < MIN_BUCKETS_FOR_TREND:
        return None
    slopes: list[float] = []
    for i in range(n):
        for j in range(i + 1, n):
            dx = xs[j] - xs[i]
            if dx == 0:
                continue
            slopes.append((ys[j] - ys[i]) / dx)
    if not slopes:
        return None
    slope = median(slopes)
    intercept = median(ys[i] - slope * xs[i] for i in range(n))
    return TrendFit(slope=slope, intercept=intercept, method="theil_sen")


def _compute_hit_at(
    *,
    fit: TrendFit,
    now: datetime,
    now_pct: float | None,
    projected_pct: float,
    total_window_secs: float,
) -> str | None:
    """ISO timestamp at which the trend crosses the limit, or None.

    The line is anchored at (now, now_pct) with the regression's slope, so
    `hit_secs_from_now = (LIMIT - now_pct) / slope`. This matches the
    anchor-at-now projection used everywhere else in the pipeline.

    Suppressed when:
    - the anchored projection doesn't reach the limit
    - slope is non-positive (line would never cross 100 going forward)
    - the card is already exhausted
    - the hit lies further than HORIZON_CAP_MULTIPLIER × window into the future
      (a noisy slope shouldn't extrapolate "weeks from now" from "hours of data")
    """
    if projected_pct < LIMIT_PCT:
        return None
    if fit.slope <= 0:
        return None
    if now_pct is None or now_pct >= EXHAUSTED_PCT:
        return None
    remaining_pct = LIMIT_PCT - now_pct
    if remaining_pct <= 0:
        return None
    hit_secs_from_now = remaining_pct / fit.slope
    if hit_secs_from_now > HORIZON_CAP_MULTIPLIER * total_window_secs:
        return None
    return (now + timedelta(seconds=hit_secs_from_now)).isoformat()


def _classify_status(
    *,
    now_pct: float | None,
    projected_pct: float,
    projected_pct_raw: float,
    hit_at: str | None,
) -> str:
    """Bucket a forecast into one of the status labels.

    `decelerating` fires when the regression line at end-of-window dips below
    the current cumulative position (i.e., the downward clamp would otherwise
    mask the slowdown) AND the card is in the matters-zone (>= 80%). For
    cumulative monotonic data, OLS/Theil-Sen slope is always non-negative,
    so a literal "slope < 0" trigger almost never fires — comparing raw
    projection vs. current is the actionable signal.
    """
    if now_pct is not None and now_pct >= EXHAUSTED_PCT:
        return "exhausted"
    if (
        now_pct is not None
        and now_pct >= DECELERATING_NOW_PCT_THRESHOLD
        and projected_pct_raw < now_pct
    ):
        return "decelerating"
    if now_pct is not None and (projected_pct - now_pct) < STABLE_PCT_EPSILON:
        return "stable"
    if projected_pct >= LIMIT_PCT or hit_at:
        return "risk"
    if projected_pct >= WARN_PCT:
        return "warn"
    return "ok"


def _make_entry(
    card: LimitCard,
    *,
    status: str,
    window_start: datetime,
    samples_used: int,
    confidence: float,
    now_state: _NowState,
    projection: _Projection = _Projection(),
    slope: float | None = None,
    method: str = "linear",
    series: list[dict[str, float | str]] | None = None,
) -> ForecastEntry:
    return ForecastEntry(
        provider_id=card.provider_id or "",
        account_id=card.account_id,
        account_label=card.account_label,
        model_id=card.model_id,
        service_name=card.service_name,
        window_type=card.window_type,
        variant=card.variant,
        unit_type=card.unit_type,
        now_used=now_state.used,
        now_pct=now_state.pct,
        projected_used=projection.used,
        projected_pct=projection.pct,
        projected_limit_hit_at=projection.hit_at,
        limit_value=card.limit_value,  # type: ignore[arg-type]  # caller verified non-None
        reset_at=card.reset_at,  # type: ignore[arg-type]  # caller verified non-None
        window_start=window_start.isoformat(),
        samples_used=samples_used,
        confidence=confidence,
        status=status,
        method=method,
        slope=slope,
        # Glide-path target shares the same value as confidence × 100 by construction
        # (both come from elapsed/total_window). Exposed separately for clarity:
        # this lets the UI render "where you should be" without overloading the
        # "confidence" semantic. See ForecastEntry docstring.
        glide_pct=confidence * LIMIT_PCT,
        series=series,
    )


def _build_series_payload(
    series_data: _SeriesData,
    window_start: datetime,
) -> list[dict[str, float | str]] | None:
    """Return the cumulative-pct trajectory as [{ts, pct}, ...] for drill-down.

    Returns None if no series data is available.
    """
    xs, ys = series_data.xs, series_data.ys
    if not xs or not ys or len(xs) != len(ys):
        return None
    return [
        {"ts": (window_start + timedelta(seconds=x)).isoformat(), "pct": float(y)}
        for x, y in zip(xs, ys, strict=False)
    ]


def _build_forecast_entry(  # noqa: PLR0913 — central pipeline helper; kw-only args document the contract
    card: LimitCard,
    *,
    window_start: datetime,
    confidence: float,
    samples_used: int,
    now_state: _NowState,
    fit: TrendFit | None,
    series_data: _SeriesData,
    total_window_secs: float,
    now: datetime,
    limit_value: float,
    include_series: bool = False,
) -> ForecastEntry:
    """Apply the shared classification + clamp + hit-at pipeline.

    This is the single place where projection clamping, status classification, and
    hit-at extrapolation live. Per-unit-type callers (token/percent/currency) only
    differ in how the cumulative-pct series is built; the projection logic is shared.
    """
    series_payload = _build_series_payload(series_data, window_start) if include_series else None
    ys = series_data.ys

    if fit is None:
        return _make_entry(
            card=card,
            status="insufficient_data",
            window_start=window_start,
            samples_used=samples_used,
            confidence=confidence,
            now_state=now_state,
            series=series_payload,
        )

    now_pct = now_state.pct
    # Raw regression projection — kept ONLY as a deceleration signal.
    # The actual reported projection is anchored at (now, now_pct).
    projected_pct_raw = fit.intercept + fit.slope * total_window_secs

    elapsed_now = (now - window_start).total_seconds()
    remaining_from_now = max(0.0, total_window_secs - elapsed_now)
    anchor_pct = now_pct if now_pct is not None else (ys[-1] if ys else 0.0)
    # Safety floor: Theil-Sen on monotonic data should give slope >= 0, but
    # floating-point noise on near-zero slope could nudge it negative.
    projected_pct = max(anchor_pct + fit.slope * remaining_from_now, anchor_pct)
    projected_used = projected_pct / LIMIT_PCT * limit_value

    hit_at = _compute_hit_at(
        fit=fit,
        now=now,
        now_pct=now_pct,
        projected_pct=projected_pct,
        total_window_secs=total_window_secs,
    )

    status = _classify_status(
        now_pct=now_pct,
        projected_pct=projected_pct,
        projected_pct_raw=projected_pct_raw,
        hit_at=hit_at,
    )

    # Map status → returned projected values. Preserves prior behavior, including
    # the stable case where projected_used is computed from the clamped projection
    # but projected_pct is set to now_pct (a tiny numeric drift, kept for parity).
    if status == "exhausted":
        projection = _Projection(used=limit_value, pct=LIMIT_PCT)
    elif status == "stable":
        projection = _Projection(used=projected_used, pct=now_pct)
    elif status == "decelerating":
        # Report current position; the clamp would have set projected ≈ current.
        projection = _Projection(used=now_state.used, pct=now_pct)
    elif status == "risk":
        projection = _Projection(used=limit_value, pct=LIMIT_PCT, hit_at=hit_at)
    else:  # warn | ok
        projection = _Projection(used=projected_used, pct=projected_pct)

    return _make_entry(
        card=card,
        status=status,
        window_start=window_start,
        samples_used=samples_used,
        confidence=confidence,
        now_state=now_state,
        projection=projection,
        slope=fit.slope,
        method=fit.method,
        series=series_payload,
    )


def _fetch_hourly_buckets(
    session: Session,
    *,
    provider_id: str,
    account_id: str,
    model_id: str | None,
    since: datetime,
    until: datetime,
) -> list[tuple[datetime, int]]:
    """Return (hour_bucket_ts, token_sum) pairs from usage_events, ordered oldest-first.

    Tokens counted: tokens_input + tokens_output + tokens_cache_read + tokens_cache_create.
    tokens_reasoning is excluded (it's a sub-type of output, already counted there).
    """
    sql = text(
        """
        SELECT
            strftime('%Y-%m-%d %H:00:00', ts) AS hour_bucket,
            SUM(tokens_input + tokens_output + tokens_cache_read + tokens_cache_create) AS toks
        FROM usage_events
        WHERE provider_id = :provider_id
          AND account_id  = :account_id
          AND ts >= :since
          AND ts <= :until
          AND (:model_id IS NULL OR model_id = :model_id)
        GROUP BY hour_bucket
        ORDER BY hour_bucket ASC
        """
    )

    # SQLite stores datetimes as naive UTC strings ("2026-05-08 17:00:00.000000").
    # Passing an ISO-8601 string with 'T' separator + '+00:00' offset breaks SQLite
    # string comparisons because 'T' (ASCII 84) > ' ' (ASCII 32), making the bound
    # compare as lexicographically larger than stored values. Strip to naive UTC.
    def _naive_utc_str(dt: datetime) -> str:
        return dt.astimezone(UTC).strftime("%Y-%m-%d %H:%M:%S.%f")

    rows = session.exec(  # type: ignore[call-overload]
        sql,
        params={
            "provider_id": provider_id,
            "account_id": account_id,
            "since": _naive_utc_str(since),
            "until": _naive_utc_str(until),
            "model_id": model_id,
        },
    ).all()

    result: list[tuple[datetime, int]] = []
    for row in rows:
        # Parse the hour bucket string to a UTC datetime
        try:
            ts = datetime.strptime(str(row.hour_bucket), "%Y-%m-%d %H:%M:%S").replace(tzinfo=UTC)
        except ValueError:
            continue
        result.append((ts, int(row.toks or 0)))
    return result


def _resolve_window(card: LimitCard, now: datetime) -> tuple[datetime, datetime, float] | None:
    """Parse reset_at and compute (window_start, reset_at_dt, total_window_secs).

    Returns None if reset_at is missing/unparseable or window_type is unknown.
    Handles rolling window_type with a 30-day default.
    """
    if not card.reset_at:
        return None
    effective_window_type = card.window_type
    if effective_window_type == "rolling":
        effective_window_type = "monthly"
    if effective_window_type not in WINDOW_DURATIONS:
        return None
    try:
        reset_at_dt = datetime.fromisoformat(card.reset_at)
        if reset_at_dt.tzinfo is None:
            reset_at_dt = reset_at_dt.replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None
    window_duration = WINDOW_DURATIONS[effective_window_type]
    window_start = reset_at_dt - window_duration
    if window_start > now:
        window_start = now - window_duration
    total_window_secs = (reset_at_dt - window_start).total_seconds()
    return window_start, reset_at_dt, total_window_secs


def _confidence_and_elapsed(
    window_start: datetime, total_window_secs: float, now: datetime
) -> tuple[float, float]:
    """Return (confidence, elapsed_secs) for a window."""
    elapsed_secs = (now - window_start).total_seconds()
    confidence = max(
        0.0, min(1.0, elapsed_secs / total_window_secs if total_window_secs > 0 else 0.0)
    )
    return confidence, elapsed_secs


#: Pre-fetched hourly token buckets keyed by (provider_id, account_id).
#: Each value is a list of (hour_ts, model_id, tokens) rows; model_id is "" for null.
BucketCache = dict[tuple[str, str], list[tuple[datetime, str, int]]]


def compute_forecast(
    card: LimitCard,
    session: Session,
    now: datetime | None = None,
    *,
    bucket_cache: BucketCache | None = None,
    include_series: bool = False,
) -> ForecastEntry | None:
    """Dispatch to the appropriate forecast method based on unit_type.

    `now` is threaded through every helper so all clock reads for a single
    forecast share one timestamp — otherwise separate reads could straddle a
    window boundary and skew the trajectory. Batch callers
    (`compute_all_forecasts`) should capture once and pass through.

    `bucket_cache`, when provided, replaces per-card hourly bucket SQL with
    in-memory filtering — populated by `compute_all_forecasts` to avoid N+1.
    """
    if now is None:
        now = datetime.now(UTC)
    if card.is_unlimited:
        return None
    if card.limit_value is None or card.limit_value <= 0:
        # Allow percent cards with limit_value=100 to pass
        if card.unit_type != "percent":
            return None
    if not card.reset_at:
        return None
    if card.unit == "pay-as-you-go":
        return None
    # Normalize singular 'token' to 'tokens'
    effective_unit_type = card.unit_type
    if effective_unit_type == "token":
        effective_unit_type = "tokens"

    if effective_unit_type in ("percent",):
        return _compute_percent_forecast(
            card,
            session,
            effective_unit_type,
            now=now,
            bucket_cache=bucket_cache,
            include_series=include_series,
        )
    if effective_unit_type in ("currency", "credits"):
        return _compute_currency_forecast(card, session, now=now, include_series=include_series)
    if effective_unit_type in ("tokens", "generic"):
        return _compute_token_forecast(
            card, session, now=now, bucket_cache=bucket_cache, include_series=include_series
        )
    # Unsupported unit types (requests, minutes, etc.) — insufficient data
    return None


def _buckets_for_card(
    session: Session,
    *,
    bucket_cache: BucketCache | None,
    provider_id: str,
    account_id: str,
    model_id: str | None,
    since: datetime,
    until: datetime,
) -> list[tuple[datetime, int]]:
    """Return hourly token buckets for one card. Slices from cache when available,
    else falls back to a per-card SQL fetch."""
    if bucket_cache is None or (provider_id, account_id) not in bucket_cache:
        return _fetch_hourly_buckets(
            session,
            provider_id=provider_id,
            account_id=account_id,
            model_id=model_id,
            since=since,
            until=until,
        )
    raw = bucket_cache[(provider_id, account_id)]
    by_hour: dict[datetime, int] = {}
    for ts, m_id, toks in raw:
        if ts < since or ts > until:
            continue
        if model_id is not None and m_id != model_id:
            continue
        by_hour[ts] = by_hour.get(ts, 0) + toks
    return sorted(by_hour.items())


def _compute_token_forecast(
    card: LimitCard,
    session: Session,
    now: datetime,
    *,
    bucket_cache: BucketCache | None = None,
    include_series: bool = False,
) -> ForecastEntry | None:
    """Forecast for token-denominated cards."""
    result = _resolve_window(card, now)
    if result is None:
        return None
    window_start, _reset_at_dt, total_window_secs = result
    confidence, _elapsed_secs = _confidence_and_elapsed(window_start, total_window_secs, now)

    if card.limit_value is None or card.limit_value <= 0:
        return None

    buckets = _buckets_for_card(
        session,
        bucket_cache=bucket_cache,
        provider_id=card.provider_id or "",
        account_id=card.account_id or "",
        model_id=card.model_id,
        since=window_start,
        until=now,
    )

    now_pct: float | None
    if card.unit_type == "percent":
        now_pct = card.used_value
    elif card.used_value is not None:
        now_pct = card.used_value / card.limit_value * LIMIT_PCT
    else:
        now_pct = None
    now_state = _NowState(used=card.used_value, pct=now_pct)

    if len(buckets) < MIN_BUCKETS_FOR_TREND:
        return _make_entry(
            card=card,
            status="insufficient_data",
            window_start=window_start,
            samples_used=len(buckets),
            confidence=confidence,
            now_state=now_state,
        )

    cumulative_tokens = 0
    xs: list[float] = []
    ys: list[float] = []
    for bucket_ts, toks in buckets:
        cumulative_tokens += toks
        elapsed = (bucket_ts - window_start).total_seconds()
        pct = cumulative_tokens / card.limit_value * LIMIT_PCT
        xs.append(elapsed)
        ys.append(pct)

    return _build_forecast_entry(
        card,
        window_start=window_start,
        confidence=confidence,
        samples_used=len(buckets),
        now_state=now_state,
        fit=_fit_trend(xs, ys),
        series_data=_SeriesData(xs=xs, ys=ys),
        total_window_secs=total_window_secs,
        now=now,
        limit_value=card.limit_value,
        include_series=include_series,
    )


def _compute_percent_forecast(
    card: LimitCard,
    session: Session,
    effective_unit_type: str,
    now: datetime,
    *,
    bucket_cache: BucketCache | None = None,
    include_series: bool = False,
) -> ForecastEntry | None:
    """Forecast for percent-denominated cards (unit_type='percent').

    Uses the card's own pct_used as 'now' position, then derives a consumption
    rate from hourly token usage events to project forward. For percent cards,
    we know the current gauge position and the limit (usually 100%). We
    extrapolate by computing how fast tokens are burning relative to the window.
    """
    result = _resolve_window(card, now)
    if result is None:
        return None
    window_start, reset_at_dt, total_window_secs = result
    confidence, elapsed_secs = _confidence_and_elapsed(window_start, total_window_secs, now)

    now_pct: float | None = None
    if card.pct_used is not None:
        now_pct = card.pct_used
    elif card.used_value is not None and card.limit_value and card.limit_value > 0:
        now_pct = card.used_value / card.limit_value * LIMIT_PCT
    elif card.used_value is not None:
        now_pct = card.used_value  # already a percentage when limit=100
    now_state = _NowState(used=card.used_value, pct=now_pct)

    buckets = _buckets_for_card(
        session,
        bucket_cache=bucket_cache,
        provider_id=card.provider_id or "",
        account_id=card.account_id or "",
        model_id=card.model_id,
        since=window_start,
        until=now,
    )

    if len(buckets) < MIN_BUCKETS_FOR_TREND or now_pct is None:
        return _make_entry(
            card=card,
            status="insufficient_data",
            window_start=window_start,
            samples_used=len(buckets),
            confidence=confidence,
            now_state=now_state,
        )

    cumulative_tokens = 0
    xs: list[float] = []
    ys: list[float] = []
    total_tokens_in_window = sum(toks for _, toks in buckets)
    if total_tokens_in_window == 0:
        # No window-relevant burn: pin projection to current state.
        return _make_entry(
            card=card,
            status="stable",
            window_start=window_start,
            samples_used=len(buckets),
            confidence=confidence,
            now_state=now_state,
            projection=_Projection(used=card.used_value, pct=now_pct),
        )

    # Tokens per percentage point = total_tokens / pct_change_covered.
    # We know pct_used at "now" from the card; tokens_in_window maps to that pct.
    token_per_pct = total_tokens_in_window / now_pct if now_pct > 0 else 1.0

    for bucket_ts, toks in buckets:
        cumulative_tokens += toks
        elapsed = (bucket_ts - window_start).total_seconds()
        pct = cumulative_tokens / token_per_pct if token_per_pct > 0 else 0.0
        xs.append(elapsed)
        ys.append(pct)

    return _build_forecast_entry(
        card,
        window_start=window_start,
        confidence=confidence,
        samples_used=len(buckets),
        now_state=now_state,
        fit=_fit_trend(xs, ys),
        series_data=_SeriesData(xs=xs, ys=ys),
        total_window_secs=total_window_secs,
        now=now,
        limit_value=card.limit_value or LIMIT_PCT,
        include_series=include_series,
    )


def _compute_currency_forecast(
    card: LimitCard, session: Session, now: datetime, *, include_series: bool = False
) -> ForecastEntry | None:
    """Forecast for currency-denominated cards (unit_type='currency' or 'credits').

    Uses daily cost_usd from period rollups for weekly+ windows; falls back to
    hourly cost from usage_events for session/daily windows (where daily rollups
    yield too few buckets to fit).
    """
    from app.services.queries.forecast import query_cost_buckets, query_cost_hourly

    result = _resolve_window(card, now)
    if result is None:
        return None
    window_start, _reset_at_dt, total_window_secs = result
    confidence, _elapsed_secs = _confidence_and_elapsed(window_start, total_window_secs, now)

    now_pct: float | None = None
    if card.pct_used is not None:
        now_pct = card.pct_used
    elif card.used_value is not None and card.limit_value and card.limit_value > 0:
        now_pct = card.used_value / card.limit_value * LIMIT_PCT
    now_state = _NowState(used=card.used_value, pct=now_pct)
    limit_value = card.limit_value

    if limit_value is None or limit_value <= 0:
        return _make_entry(
            card=card,
            status="insufficient_data",
            window_start=window_start,
            samples_used=0,
            confidence=confidence,
            now_state=now_state,
        )

    # Sub-day windows need finer bucketing than the daily rollup table provides.
    use_hourly = total_window_secs <= 24 * 3600
    xs: list[float] = []
    ys: list[float] = []
    cumulative_cost = 0.0
    samples_used = 0

    if use_hourly:
        hourly = query_cost_hourly(
            session,
            provider_id=card.provider_id or "",
            account_id=card.account_id or "",
            since=window_start,
            until=now,
        )
        samples_used = len(hourly)
        for bucket_ts, cost, _toks in hourly:
            cumulative_cost += cost
            elapsed = (bucket_ts - window_start).total_seconds()
            xs.append(elapsed)
            ys.append(cumulative_cost / limit_value * LIMIT_PCT)
    else:
        rows = query_cost_buckets(
            session,
            provider_id=card.provider_id or "",
            account_id=card.account_id or "",
            since_key=window_start.strftime("%Y-%m-%d"),
            until_key=now.strftime("%Y-%m-%d"),
        )
        samples_used = len(rows)
        for period_key, daily_cost, _daily_tokens in rows:
            cumulative_cost += daily_cost
            day_ts = datetime.strptime(period_key, "%Y-%m-%d").replace(tzinfo=UTC)
            elapsed = (day_ts - window_start).total_seconds()
            xs.append(elapsed)
            ys.append(cumulative_cost / limit_value * LIMIT_PCT)

    if samples_used < MIN_BUCKETS_FOR_TREND:
        return _make_entry(
            card=card,
            status="insufficient_data",
            window_start=window_start,
            samples_used=samples_used,
            confidence=confidence,
            now_state=now_state,
        )

    return _build_forecast_entry(
        card,
        window_start=window_start,
        confidence=confidence,
        samples_used=samples_used,
        now_state=now_state,
        fit=_fit_trend(xs, ys),
        series_data=_SeriesData(xs=xs, ys=ys),
        total_window_secs=total_window_secs,
        now=now,
        limit_value=limit_value,
        include_series=include_series,
    )


def compute_all_forecasts(cards: list[LimitCard], session: Session) -> ForecastResponse:
    from app.services.queries.forecast import query_hourly_token_buckets_batch

    forecasts: list[ForecastEntry] = []
    summary: dict[str, int] = {
        "risk": 0,
        "warn": 0,
        "ok": 0,
        "insufficient_data": 0,
        "stable": 0,
        "exhausted": 0,
        "decelerating": 0,
    }

    now = datetime.now(UTC)

    # Pre-fetch hourly token buckets in one SQL scan to avoid N+1 across cards.
    # Currency cards have their own per-card daily-rollup query — not batched here.
    earliest_window_start: datetime | None = None
    for card in cards:
        if card.is_unlimited or not card.reset_at or card.unit_type in ("currency", "credits"):
            continue
        win = _resolve_window(card, now)
        if win is None:
            continue
        ws = win[0]
        if earliest_window_start is None or ws < earliest_window_start:
            earliest_window_start = ws

    bucket_cache: BucketCache | None = None
    if earliest_window_start is not None:
        bucket_cache = query_hourly_token_buckets_batch(
            session, since=earliest_window_start, until=now
        )

    for card in cards:
        entry = compute_forecast(card, session, now=now, bucket_cache=bucket_cache)
        if entry is not None:
            forecasts.append(entry)
            # Defensive bump: a forgotten status key would silently drop counts here.
            summary[entry.status] = summary.get(entry.status, 0) + 1

    return ForecastResponse(
        forecasts=forecasts,
        summary=summary,
        generated_at=now.isoformat(),
    )
