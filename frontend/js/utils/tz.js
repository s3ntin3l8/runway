// Timezone resolution + formatting helpers. Single source of truth for how
// the dashboard renders timestamps in the user's local zone.
//
// Resolution chain (highest priority first):
//   1. SystemConfig.user_timezone — explicit dashboard-side override
//   2. backend TZ env var          — deployment-level default (Docker, etc.)
//   3. browser auto-detect         — Intl.DateTimeFormat()
//
// The first two come from /api/v1/system/app-config and are stashed on
// `window.runwayConfig` by app.js bootstrap. If that hasn't loaded yet (or
// fails), we fall through to browser detection so the UI still renders.

let _cached = null;

export function setRunwayConfig(cfg) {
    window.runwayConfig = { ...(window.runwayConfig || {}), ...(cfg || {}) };
    _cached = null;
}

export function getUserTz() {
    if (_cached) return _cached;
    const cfg = window.runwayConfig || {};
    const tz =
        cfg.user_timezone ||
        cfg.env_timezone ||
        Intl.DateTimeFormat().resolvedOptions().timeZone ||
        'UTC';
    _cached = tz;
    return tz;
}

// Format helpers — always pass `timeZone` so the result is deterministic
// regardless of how the browser parses the input string.

export function formatLocalTime(iso, opts = { hour: '2-digit', minute: '2-digit' }) {
    if (!iso) return '—';
    return new Date(iso).toLocaleTimeString([], { ...opts, timeZone: getUserTz() });
}

export function formatLocalDateTime(iso, opts = {}) {
    if (!iso) return '—';
    return new Date(iso).toLocaleString([], { timeZone: getUserTz(), ...opts });
}

export function formatLocalDate(iso, opts = { month: 'short', day: 'numeric' }) {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString([], { ...opts, timeZone: getUserTz() });
}

// Format a Unix epoch (seconds) the same way — used by chart bucket labels
// where the source isn't an ISO string.
export function formatLocalFromEpoch(epochSeconds, opts = {}) {
    return formatLocalDateTime(new Date(epochSeconds * 1000).toISOString(), opts);
}
