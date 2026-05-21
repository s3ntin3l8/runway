// Number / currency / token formatters used across the dashboard.
//
// Two flavours of "compact number" exist intentionally and are NOT unified:
//   - formatNumber: K/M/B with 1 decimal; preserves integers untouched. Used
//     in components.js for general counts.
//   - formatTokens: K/M/B with 2 decimals on B and M, 0 decimals on K. Used
//     in modal panes where tokens are the primary value.
// Differences are display-driven; keep both rather than picking one and
// silently changing every modal's render.

export function formatNumber(num) {
    if (num === null || num === undefined || isNaN(num)) return '—';
    const absNum = Math.abs(num);
    if (absNum >= 1e9) return `${(num / 1e9).toFixed(1)}B`;
    if (absNum >= 1e6) return `${(num / 1e6).toFixed(1)}M`;
    if (absNum >= 1e3) return `${(num / 1e3).toFixed(1)}K`;
    if (Number.isInteger(num)) return num.toString();
    return num.toFixed(1);
}

const _formatterCache = new Map();
function _getCurrencyFormatter(currencyCode) {
    const code = (currencyCode || 'USD').toUpperCase();
    const locale = (typeof navigator !== 'undefined' && navigator.language) || 'en-US';
    const key = `${locale}|${code}`;
    let f = _formatterCache.get(key);
    if (!f) {
        try {
            f = new Intl.NumberFormat(locale, {
                style: 'currency', currency: code,
                currencyDisplay: 'narrowSymbol',
                minimumFractionDigits: 2, maximumFractionDigits: 2,
            });
        } catch {
            f = new Intl.NumberFormat(locale, {
                style: 'currency', currency: 'USD',
                currencyDisplay: 'narrowSymbol',
                minimumFractionDigits: 2, maximumFractionDigits: 2,
            });
        }
        _formatterCache.set(key, f);
    }
    return f;
}

export function formatCurrency(amount, currencyCode) {
    if (amount === null || amount === undefined || isNaN(amount)) return '—';
    return _getCurrencyFormatter(currencyCode).format(amount);
}

// Modal-flavour token formatter. Zero renders as literal '0' (not '—') because
// modal panes show explicit zero rows.
export function formatTokens(val) {
    if (val == null || val === 0) return '0';
    if (val >= 1e9) return (val / 1e9).toFixed(2) + 'B';
    if (val >= 1e6) return (val / 1e6).toFixed(2) + 'M';
    if (val >= 1e3) return (val / 1e3).toFixed(0) + 'K';
    return String(val);
}

// Modal-flavour cost formatter. Distinguishes 0 (literal $0.00) from
// sub-cent (< $0.01) from null/missing (—) — all three render differently
// in cost panes. Locale-aware: uses navigator.language for separators/symbols.
export function formatCost(usd, currencyCode = 'USD') {
    if (usd == null) return '—';
    const f = _getCurrencyFormatter(currencyCode);
    if (usd === 0) return f.format(0);
    if (usd > 0 && usd < 0.01) return '< ' + f.format(0.01);
    return f.format(usd);
}
