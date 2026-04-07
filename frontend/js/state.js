export const STATE = {
    compact: false,
    remaining: false,
    data: []
};

export const HEALTH_CONFIG = {
    good:     { dot: 'dot-good',     card: 'health-good',     badge: 'text-emerald-400', bar: '#22c55e', label: 'GOOD' },
    warning:  { dot: 'dot-warning',  card: 'health-warning',  badge: 'text-amber-400',   bar: '#f59e0b', label: 'WARN' },
    critical: { dot: 'dot-critical', card: 'health-critical', badge: 'text-red-400',      bar: '#ef4444', label: 'CRIT' },
    unknown:  { dot: 'dot-unknown',  card: 'health-unknown',  badge: 'text-zinc-500',     bar: '#3f3f46', label: '——' },
};
