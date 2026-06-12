// Shared quota clustering + status utilities (port of frontend/js/utils/quota.js).
//
// Clustering uses an explicit collector-set `quota_pool_id` rather than
// behavioral similarity. Cards with matching non-null pool_id share a
// physical quota; everything else stands alone. This avoids the
// Gemini-Flash + Gemini-Flash-Lite false-positive trap where two
// independent daily quotas at the same percentage and reset time got
// lumped into a fake "SHARED" pool.

import type { LimitCard } from '@/api/types';

export function sameQuota(a: LimitCard, b: LimitCard): boolean {
  return a.quota_pool_id != null && a.quota_pool_id === b.quota_pool_id;
}

export function clusterPools(cards: LimitCard[]): LimitCard[][] {
  const clusters: LimitCard[][] = [];
  const seen = new Set<LimitCard>();
  for (const card of cards) {
    if (seen.has(card)) continue;
    const cluster = [card];
    seen.add(card);
    for (const other of cards) {
      if (seen.has(other)) continue;
      if (sameQuota(card, other)) {
        cluster.push(other);
        seen.add(other);
      }
    }
    clusters.push(cluster);
  }
  return clusters;
}

// Compact display label listing a cluster's model names. Strips "AG: "
// provider prefix noise; truncates to "+N" beyond 2 names.
export function clusterModelLabel(cluster: LimitCard[]): string {
  const names = cluster
    .map((c) => (c.service_name || c.model_id || '').replace(/^AG:\s*/i, ''))
    .filter(Boolean);
  if (names.length <= 2) return names.join(' · ');
  return names.slice(0, 2).join(' · ') + ` +${names.length - 2}`;
}

// --- Status semantics ------------------------------------------------------

export type QuotaStatus = 'critical' | 'warning' | 'ok' | 'unlimited' | 'unknown';

export const CRITICAL_PCT = 90;
export const WARNING_PCT = 70;

export function statusForPct(pct: number | null | undefined): QuotaStatus {
  if (pct === null || pct === undefined || Number.isNaN(pct)) return 'unknown';
  if (pct >= CRITICAL_PCT) return 'critical';
  if (pct >= WARNING_PCT) return 'warning';
  return 'ok';
}

// Card → semantic status token. Error cards and unlimited cards take
// precedence over the percentage thresholds.
export function cardStatus(card: LimitCard): QuotaStatus {
  if (card.error_type) return 'critical';
  if (card.is_unlimited) return 'unlimited';
  return statusForPct(card.pct_used);
}
