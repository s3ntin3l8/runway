// Helpers for CumulativeModelBucket / CumulativeBucket aggregations.
// These rollups share the same per-component token fields as the lifetime
// `TokenUsage` shape (see tokenUsageTotal in quota.ts) but use a slightly
// different field-naming convention (tokens_* vs *), so they need their own
// sum/has helpers.

import type { CumulativeModelBucket } from '@/api/types';

// Sum the per-component token counts of a cumulative bucket. Honours the
// shared exclude-cache toggle — same semantics as tokenUsageTotal in quota.ts
// but over the aggregated monthly/lifetime rollup shape.
export function sumTokens(
  b: CumulativeModelBucket | null | undefined,
  excludeCache = false,
): number {
  if (!b) return 0;
  return (
    (b.tokens_input ?? 0) +
    (b.tokens_output ?? 0) +
    (excludeCache ? 0 : (b.tokens_cache_read ?? 0) + (b.tokens_cache_create ?? 0)) +
    (b.tokens_reasoning ?? 0)
  );
}

// True when the bucket has any token data worth rendering — used to gate
// donut/bar charts so an all-zero rollup doesn't render an empty pie ring.
// Honours `excludeCache` so the gate matches what the chart will actually
// draw: with the toggle on, a bucket carrying only cache components would
// otherwise pass this check but render empty after `TokenDonut` filters
// the cache slices out. Type predicate so callers can pass a nullable
// bucket and use it non-null after the check.
export function hasTokenData(
  b: CumulativeModelBucket | null | undefined,
  excludeCache = false,
): b is CumulativeModelBucket {
  return sumTokens(b, excludeCache) > 0;
}
