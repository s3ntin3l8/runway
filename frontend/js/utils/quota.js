/**
 * Shared quota clustering utilities.
 * Used by fleet-commander.js (pool bars) and dashboard.js (hero card label).
 *
 * Clustering uses an explicit collector-set `quota_pool_id` rather than
 * behavioral similarity. Cards with matching non-null pool_id share a
 * physical quota; everything else stands alone. This avoids the
 * Gemini-Flash + Gemini-Flash-Lite false-positive trap where two
 * independent daily quotas at the same percentage and reset time got
 * lumped into a fake "SHARED" pool.
 */

/**
 * Returns true when cards a and b carry the same physical quota signal.
 * @param {object} a
 * @param {object} b
 * @returns {boolean}
 */
export function sameQuota(a, b) {
    return a.quota_pool_id != null && a.quota_pool_id === b.quota_pool_id;
}

/**
 * Cluster an array of cards by shared physical quota.
 * Returns an array of clusters (each cluster is an array of cards).
 * Singletons have length 1.
 * @param {object[]} cards
 * @returns {object[][]}
 */
export function clusterPools(cards) {
    const clusters = [];
    const seen = new Set();
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

/**
 * Build a compact display label listing a cluster's model names.
 * Strips "AG: " provider prefix noise. Truncates to "+N" form beyond 2 names
 * to keep the label narrow enough to fit a single pool row / hero quota line.
 * @param {object[]} cluster
 * @returns {string}
 */
export function clusterModelLabel(cluster) {
    const names = cluster
        .map(c => (c.service_name || c.model_id || '').replace(/^AG:\s*/i, ''))
        .filter(Boolean);
    if (names.length <= 2) return names.join(' · ');
    return names.slice(0, 2).join(' · ') + ` +${names.length - 2}`;
}
