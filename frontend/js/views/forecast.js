import { ensureECharts } from '../charts.js';
import { fetchForecast } from '../api.js';
import { formatLocalTime, formatLocalDate } from '../utils/tz.js';

const STATUS_COLOR = {
    exhausted: 'var(--crit)',
    risk: 'var(--crit)',
    warn: 'var(--warn)',
    decelerating: 'var(--info, #4a9eff)',
    ok: 'var(--good)',
    stable: 'var(--accent)',
    insufficient_data: 'var(--text-dim)',
};

const FORECAST_CACHE_TTL_MS = 30_000;
let _forecastCache = null;
let _forecastCacheAt = 0;
let _forecastChart = null;

let _filterWindow = '';
let _filterProvider = '';
let _sortMode = 'projected';  // 'projected' | 'hit_time'
let _showStableInChart = false;
const _expandedRowKeys = new Set();
const _seriesCache = new Map();  // key -> {data, fetchedAt}
const _drilldownCharts = new Map();  // key -> echarts instance (disposed on collapse/rerender)

const _MODEL_DISPLAY = {
    'sonnet': 'Sonnet', 'opus': 'Opus', 'haiku': 'Haiku',
    'design': 'Design', 'flash': 'Flash', 'pro': 'Pro', 'flash-lite': 'Flash Lite',
};
const _WINDOW_DISPLAY = {
    'session': 'Session', 'daily': 'Daily', 'weekly': 'Weekly', 'monthly': 'Monthly',
};

function _forecastSubtitle(entry) {
    const parts = [];
    if (entry.variant) parts.push(String(entry.variant));
    if (entry.model_id) {
        parts.push(_MODEL_DISPLAY[entry.model_id] || String(entry.model_id).replace(/-/g, ' ').replace(/\b\w/g, c => c.toUpperCase()));
    }
    const w = _WINDOW_DISPLAY[entry.window_type];
    if (w) parts.push(w);
    return parts.join(' · ');
}

async function fetchForecastCached() {
    const now = Date.now();
    if (_forecastCache && (now - _forecastCacheAt) < FORECAST_CACHE_TTL_MS) {
        return _forecastCache;
    }
    const params = {};
    if (_filterWindow) params.window_type = _filterWindow;
    if (_filterProvider) params.provider_id = _filterProvider;
    const data = await fetchForecast(params);
    _forecastCache = data;
    _forecastCacheAt = now;
    return data;
}

function _confidenceLabel(confidence) {
    if (confidence >= 0.66) return 'high';
    if (confidence >= 0.33) return '~mid';
    return '?low';
}

function _trendArrow(slope, status) {
    if (slope == null) return '<span style="color:var(--text-dim);">—</span>';
    let color = 'var(--text-dim)';
    if (status === 'risk') color = 'var(--crit)';
    else if (status === 'warn') color = 'var(--warn)';
    else if (status === 'decelerating') color = 'var(--info, #4a9eff)';
    else if (status === 'ok') color = 'var(--good)';
    const eps = 1e-9;
    let glyph = '→';
    if (slope > eps) glyph = '↑';
    else if (slope < -eps) glyph = '↓';
    return `<span style="color:${color};font-weight:600;">${glyph}</span>`;
}

// "On pace" tolerance — matches fleet-commander.js so the dashboard and
// forecast page agree on ahead/on/behind for the same card.
const PACE_TOLERANCE_PCT = 4.0;

function _paceCell(glidePct, nowPct) {
    if (glidePct == null) return '<span style="color:var(--text-dim);">—</span>';
    const pct = glidePct.toFixed(0) + '%';
    if (nowPct == null) {
        return `<span style="color:var(--text-dim);">${pct}</span>`;
    }
    const delta = nowPct - glidePct;
    let glyph = '→', color = 'var(--text-dim)', label = 'on pace';
    if (delta > PACE_TOLERANCE_PCT) {
        glyph = '↑'; color = 'var(--warn)'; label = 'ahead of pace';
    } else if (delta < -PACE_TOLERANCE_PCT) {
        glyph = '↓'; color = 'var(--good)'; label = 'under pace';
    }
    return `<span title="${label} (now ${nowPct.toFixed(1)}% vs glide-path ${pct})"><span style="color:var(--text-dim);">${pct}</span> <span style="color:${color};font-weight:600;">${glyph}</span></span>`;
}

function _rowKey(entry) {
    return [entry.provider_id, entry.account_id || '', entry.model_id || '', entry.window_type, entry.variant || ''].join('|');
}

function _sortForecasts(arr) {
    if (_sortMode === 'hit_time') {
        // Soonest hits first; nulls last.
        return [...arr].sort((a, b) => {
            const ah = a.projected_limit_hit_at ? Date.parse(a.projected_limit_hit_at) : Infinity;
            const bh = b.projected_limit_hit_at ? Date.parse(b.projected_limit_hit_at) : Infinity;
            if (ah !== bh) return ah - bh;
            return (b.projected_pct ?? -1) - (a.projected_pct ?? -1);
        });
    }
    return [...arr].sort((a, b) => (b.projected_pct ?? -1) - (a.projected_pct ?? -1));
}

function _renderKpi(summary) {
    const kpiCrit = document.getElementById('forecast-kpi-crit');
    const kpiOk = document.getElementById('forecast-kpi-ok');
    if (!kpiCrit || !kpiOk) return;

    const critItems = [
        { label: 'RISK', key: 'risk', color: 'var(--crit)' },
        { label: 'EXHAUSTED', key: 'exhausted', color: 'var(--crit)' },
        { label: 'WARN', key: 'warn', color: 'var(--warn)' },
    ];
    
    const okItems = [
        { label: 'OK', key: 'ok', color: 'var(--good)' },
        { label: 'COOLING', key: 'decelerating', color: 'var(--info, #4a9eff)' },
        { label: 'STABLE', key: 'stable', color: 'var(--accent)' },
        { label: 'NO DATA', key: 'insufficient_data', color: 'var(--text-dim)' },
    ];

    const renderGroup = (items) => items.map(({ label, key, color }) => `
        <div style="background:var(--surface);border:1px solid var(--hairline);padding:12px 10px;text-align:center;border-radius:4px;">
            <div style="font-size:24px;font-weight:700;color:${color};font-family:'B612 Mono',monospace;line-height:1;">${summary[key] ?? 0}</div>
            <div style="font-size:9px;color:var(--text-dim);letter-spacing:0.12em;margin-top:6px;text-transform:uppercase;">${label}</div>
        </div>
    `).join('');

    kpiCrit.innerHTML = renderGroup(critItems);
    kpiOk.innerHTML = renderGroup(okItems);
}

function _renderTable(forecasts) {
    const tbody = document.getElementById('forecast-table-body');
    const empty = document.getElementById('forecast-empty');
    if (!tbody) return;

    const sorted = _sortForecasts(forecasts);

    if (sorted.length === 0) {
        tbody.innerHTML = '';
        empty?.classList.remove('hidden');
        return;
    }
    empty?.classList.add('hidden');

    const rowsHtml = sorted.map(f => {
        const color = STATUS_COLOR[f.status] || 'var(--text-dim)';
        const nowPct = f.now_pct != null ? f.now_pct.toFixed(1) + '%' : '—';

        let projPct = (f.status === 'stable' || f.status === 'exhausted' || f.projected_pct == null) ? '—' : f.projected_pct.toFixed(1) + '%';
        if (f.projected_limit_hit_at) {
            const timeStr = formatLocalTime(f.projected_limit_hit_at);
            const dateStr = formatLocalDate(f.projected_limit_hit_at);
            projPct = `100% (${dateStr} ${timeStr})`;
        }

        const conf = _confidenceLabel(f.confidence);
        const confPct = Math.round((f.confidence ?? 0) * 100);
        const confTitle = `Window elapsed: ${confPct}%. high ≥66%, mid 33–66%, low <33%.`;
        const resetDate = formatLocalDate(f.reset_at);
        const baseLabel = f.service_name || f.provider_id;
        const sub = _forecastSubtitle(f);
        const label = sub ? `${baseLabel} · ${sub}` : baseLabel;
        const trend = _trendArrow(f.slope, f.status);
        const key = _rowKey(f);
        const isExpanded = _expandedRowKeys.has(key);
        const expandClass = isExpanded ? ' expanded' : '';

        const paceCell = _paceCell(f.glide_pct, f.now_pct);

        let html = `<tr class="forecast-row${expandClass}" data-row-key="${key}" data-provider-id="${f.provider_id}" data-account-id="${f.account_id || ''}" data-window-type="${f.window_type}" style="cursor:pointer;">
            <td>${label}</td>
            <td>${f.provider_id}</td>
            <td class="num">${nowPct}</td>
            <td class="num">${paceCell}</td>
            <td class="num ht-bold" style="color:${color};">${projPct}</td>
            <td class="num">${trend}</td>
            <td class="num ht-italic" title="${confTitle}">${conf}</td>
            <td>${resetDate}</td>
            <td><span style="color:${color};text-transform:uppercase;letter-spacing:0.08em;">${f.status}</span></td>
        </tr>`;
        if (isExpanded) {
            html += `<tr class="forecast-row-detail" data-detail-for="${key}">
                <td colspan="9" style="padding:0;">
                    <div class="forecast-drilldown" data-drilldown-for="${key}" style="height:160px;padding:8px 16px;background:var(--surface);"></div>
                </td>
            </tr>`;
        }
        return html;
    }).join('');
    tbody.innerHTML = rowsHtml;

    // After insertion, re-render any expanded drill-downs.
    for (const key of _expandedRowKeys) {
        _renderRowDrilldown(key);
    }
}

async function _renderChart(forecasts) {
    await ensureECharts();
    
    const el = document.getElementById('forecast-chart');
    if (!el || typeof echarts === 'undefined') return;

    if (_forecastChart) {
        _forecastChart.dispose();
        _forecastChart = null;
    }

    // Chart forecasts with meaningful projections. Stable/no-data hidden by default;
    // user can opt in via the chart toggle.
    const chartable = forecasts.filter(f => {
        if (f.projected_pct == null || f.now_pct == null) return false;
        if (!_showStableInChart && (f.status === 'stable' || f.status === 'insufficient_data')) {
            return false;
        }
        return true;
    });
    if (chartable.length === 0) {
        el.style.display = 'none';
        return;
    }
    el.style.display = '';

    const css = getComputedStyle(document.documentElement);
    const cSurface = css.getPropertyValue('--surface').trim() || '#1a1a2e';
    const cText = css.getPropertyValue('--text').trim() || '#e0e0e0';
    const cTextDim = css.getPropertyValue('--text-dim').trim() || '#666';
    const cHairline = css.getPropertyValue('--hairline').trim() || '#2a2a3e';
    const cCrit = css.getPropertyValue('--crit').trim() || '#ff4444';
    const cWarn = css.getPropertyValue('--warn').trim() || '#ffaa00';
    const cGood = css.getPropertyValue('--good').trim() || '#00cc88';

    // Build bar chart: now_pct (solid) + delta to projected_pct (dashed stack)
    const labels = chartable.map(f => {
        const base = f.service_name || f.provider_id;
        const sub = _forecastSubtitle(f);
        return sub ? `${base} · ${sub}` : base;
    });
    const nowData = chartable.map(f => parseFloat((f.now_pct ?? 0).toFixed(1)));
    const projData = chartable.map(f => parseFloat((f.projected_pct ?? 0).toFixed(1)));
    // Glide-path tick per card — drawn as a thin horizontal mark over each bar.
    // Use scatter [categoryIndex, glide_pct] so each tick lines up with its bar.
    const glideData = chartable
        .map((f, i) => (f.glide_pct == null ? null : [i, parseFloat(f.glide_pct.toFixed(1))]))
        .filter(p => p !== null);

    const cInfo = css.getPropertyValue('--info').trim() || '#4a9eff';
    const barColors = chartable.map(f => {
        if (f.status === 'risk' || f.status === 'exhausted') return cCrit;
        if (f.status === 'warn') return cWarn;
        if (f.status === 'decelerating') return cInfo;
        if (f.status === 'stable') return cTextDim;
        if (f.status === 'insufficient_data') return cHairline;
        return cGood;
    });

    _forecastChart = echarts.init(el);
    _forecastChart.setOption({
        backgroundColor: 'transparent',
        tooltip: {
            trigger: 'axis',
            backgroundColor: cSurface,
            borderColor: cHairline,
            borderWidth: 1,
            padding: [8, 12],
            textStyle: { color: cText, fontFamily: 'B612 Mono, monospace', fontSize: 10 },
            formatter: (params) => {
                // Bar series share an index axis; scatter (glide) is on category,
                // so it may or may not be present in `params`. Locate via dataIndex.
                const barEntry = params.find(p => p.seriesType === 'bar') ?? params[0];
                const idx = barEntry?.dataIndex ?? 0;
                const name = barEntry?.name ?? '';
                const f = chartable[idx];
                if (!f) return '';

                let t = `<div style="font-weight:700;margin-bottom:8px;">${name}</div>`;
                t += `<div>Current: <span style="font-weight:600;">${(f.now_pct ?? 0).toFixed(1)}%</span></div>`;
                if (f.glide_pct != null) {
                    t += `<div style="margin-top:4px;">Pace target: <span style="font-weight:600;color:${cTextDim};">${f.glide_pct.toFixed(0)}%</span></div>`;
                }
                if (f.projected_limit_hit_at) {
                    const hitAt = new Date(f.projected_limit_hit_at);
                    const timeStr = hitAt.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
                    const dateStr = hitAt.toLocaleDateString([], { month: 'short', day: 'numeric' });
                    t += `<div style="margin-top:4px;">Projected: <span style="font-weight:600;color:var(--crit)">Hits 100% on ${dateStr} at ${timeStr}</span></div>`;
                } else {
                    t += `<div style="margin-top:4px;">Projected: <span style="font-weight:600;">${(f.projected_pct ?? 0).toFixed(1)}%</span></div>`;
                }
                return t;
            }
        },
        grid: { top: 20, left: 60, right: 20, bottom: 120, containLabel: false },
        xAxis: {
            type: 'category',
            data: labels,
            axisLabel: { color: cTextDim, fontSize: 9, fontFamily: 'B612 Mono, monospace', rotate: labels.length > 4 ? 30 : 0 },
            axisLine: { lineStyle: { color: cHairline } },
            axisTick: { show: false }
        },
        yAxis: {
            type: 'value',
            name: '%',
            min: 0,
            nameTextStyle: { color: cTextDim, fontSize: 9, fontFamily: 'B612 Mono, monospace' },
            axisLabel: { color: cTextDim, fontSize: 9, fontFamily: 'B612 Mono, monospace', formatter: v => v + '%' },
            splitLine: { lineStyle: { color: cHairline, type: 'dashed' } },
            axisLine: { show: false },
            markLine: { data: [{ yAxis: 100, lineStyle: { color: cCrit, type: 'dashed', width: 1 } }] }
        },
        series: [
            {
                name: 'Current %',
                type: 'bar',
                data: nowData,
                itemStyle: { color: (params) => barColors[params.dataIndex] + '88' },
                barMaxWidth: 40,
            },
            {
                name: 'Projected %',
                type: 'bar',
                data: projData,
                itemStyle: { color: (params) => barColors[params.dataIndex], borderRadius: [2, 2, 0, 0] },
                barMaxWidth: 40,
                barGap: '-100%',
                z: 2,
                opacity: 0.5,
            },
            {
                name: 'Pace target',
                type: 'scatter',
                data: glideData,
                // Tick mark spanning ~bar width to read as a reference line.
                symbol: 'rect',
                symbolSize: [44, 2],
                itemStyle: { color: cTextDim },
                z: 3,
                tooltip: { show: false },  // handled by axis tooltip already
            },
        ]
    });
}

function _renderWindowChips() {
    const el = document.getElementById('forecast-window-chips');
    if (!el) return;
    const windows = [
        { val: '', label: 'All windows' },
        { val: 'daily', label: 'Daily' },
        { val: 'weekly', label: 'Weekly' },
        { val: 'biweekly', label: 'Biweekly' },
        { val: 'monthly', label: 'Monthly' }
    ];
    el.innerHTML = windows.map(w => {
        const active = _filterWindow === w.val ? ' active' : '';
        return `<button class="chip${active}" data-window="${w.val}">${w.label}</button>`;
    }).join('');
}

function _disposeDrilldownChart(key) {
    const inst = _drilldownCharts.get(key);
    if (inst) {
        try { inst.dispose(); } catch (_) { /* noop */ }
        _drilldownCharts.delete(key);
    }
}

async function _renderRowDrilldown(key) {
    const el = document.querySelector(`[data-drilldown-for="${CSS.escape(key)}"]`);
    if (!el) return;
    await ensureECharts();
    if (typeof echarts === 'undefined') return;

    const cached = _seriesCache.get(key);
    const data = cached?.data;
    if (!data) {
        _disposeDrilldownChart(key);
        el.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-dim);font-size:11px;">Loading…</div>';
        return;
    }
    if (!Array.isArray(data.series) || data.series.length === 0) {
        _disposeDrilldownChart(key);
        el.innerHTML = '<div style="padding:24px;text-align:center;color:var(--text-dim);font-size:11px;">No bucket data available.</div>';
        return;
    }

    // Dispose any previous chart for this key before re-init (re-render reattaches DOM).
    _disposeDrilldownChart(key);
    el.innerHTML = '';
    const chart = echarts.init(el);
    _drilldownCharts.set(key, chart);
    const css = getComputedStyle(document.documentElement);
    const cText = css.getPropertyValue('--text').trim() || '#e0e0e0';
    const cTextDim = css.getPropertyValue('--text-dim').trim() || '#666';
    const cHairline = css.getPropertyValue('--hairline').trim() || '#2a2a3e';
    const cAccent = css.getPropertyValue('--accent').trim() || '#4a9eff';

    const points = data.series.map(p => [Date.parse(p.ts), p.pct]);
    chart.setOption({
        backgroundColor: 'transparent',
        grid: { top: 10, left: 40, right: 10, bottom: 20, containLabel: false },
        tooltip: {
            trigger: 'axis',
            formatter: (params) => {
                const p = params[0];
                const ts = new Date(p.value[0]).toLocaleString();
                return `<div style="font-size:10px;color:${cText};">${ts}<br><b>${p.value[1].toFixed(2)}%</b></div>`;
            },
        },
        xAxis: {
            type: 'time',
            axisLine: { lineStyle: { color: cHairline } },
            axisLabel: { color: cTextDim, fontSize: 9, fontFamily: 'B612 Mono, monospace' },
        },
        yAxis: {
            type: 'value',
            min: 0,
            max: 100,
            splitLine: { lineStyle: { color: cHairline, type: 'dashed' } },
            axisLabel: { color: cTextDim, fontSize: 9, formatter: v => v + '%' },
            axisLine: { show: false },
        },
        series: [{
            type: 'line',
            data: points,
            symbol: 'circle',
            symbolSize: 4,
            lineStyle: { color: cAccent, width: 1.5 },
            itemStyle: { color: cAccent },
            areaStyle: { color: cAccent, opacity: 0.08 },
        }],
    });
}

async function _toggleRowExpansion(row) {
    const key = row.dataset.rowKey;
    if (!key) return;
    if (_expandedRowKeys.has(key)) {
        _expandedRowKeys.delete(key);
        _disposeDrilldownChart(key);
    } else {
        _expandedRowKeys.add(key);
        const params = {
            provider_id: row.dataset.providerId,
            window_type: row.dataset.windowType,
            include_series: 'true',
        };
        if (row.dataset.accountId) params.account_id = row.dataset.accountId;
        try {
            const data = await fetchForecast(params);
            const entry = (data.forecasts || []).find(f => _rowKey(f) === key) || data.forecasts?.[0];
            _seriesCache.set(key, { data: entry, fetchedAt: Date.now() });
        } catch (err) {
            console.error('Drill-down fetch failed:', err);
            _seriesCache.set(key, { data: { series: [] }, fetchedAt: Date.now() });
        }
    }
    // Re-render the table to reflect new expansion state.
    const cached = await fetchForecastCached();
    _renderTable(cached.forecasts ?? []);
}

function _renderSortAndChartControls() {
    const sortEl = document.getElementById('forecast-sort-chips');
    if (sortEl) {
        const opts = [
            { val: 'projected', label: 'Sort: projected %' },
            { val: 'hit_time', label: 'Sort: hit time' },
        ];
        sortEl.innerHTML = opts.map(o => {
            const active = _sortMode === o.val ? ' active' : '';
            return `<button class="chip${active}" data-sort="${o.val}">${o.label}</button>`;
        }).join('');
    }
    const togEl = document.getElementById('forecast-show-stable-toggle');
    if (togEl) {
        togEl.innerHTML = `<button class="chip${_showStableInChart ? ' active' : ''}" data-toggle="show-stable">${
            _showStableInChart ? 'Hide stable/no-data' : 'Show stable/no-data'
        }</button>`;
    }
}

function _populateProviderFilter(forecasts) {
    const el = document.getElementById('forecast-provider-chips');
    if (!el) return;
    
    // Always recalculate unique providers from the current data
    const providers = [...new Set(forecasts.map(f => f.provider_id))].sort();
    
    let html = `<button class="chip${_filterProvider === '' ? ' active' : ''}" data-prov="">All providers</button>`;
    html += providers.map(p => {
        const active = _filterProvider === p ? ' active' : '';
        return `<button class="chip${active}" data-prov="${p}">${p}</button>`;
    }).join('');
    
    el.innerHTML = html;
}

export async function loadForecastView() {
    try {
        const data = await fetchForecastCached();
        const forecasts = data.forecasts ?? [];
        const summary = data.summary ?? {};

        _renderKpi(summary);
        _renderWindowChips();
        _populateProviderFilter(forecasts);
        _renderSortAndChartControls();
        _renderTable(forecasts);
        await _renderChart(forecasts);

        const genAt = document.getElementById('forecast-generated-at');
        if (genAt && data.generated_at) {
            genAt.textContent = 'Generated: ' + new Date(data.generated_at).toLocaleTimeString();
        }
    } catch (err) {
        console.error('Failed to load forecast view:', err);
        const tbody = document.getElementById('forecast-table-body');
        if (tbody) tbody.innerHTML = `<tr><td colspan="9" class="ht-empty">Failed to load forecast data.</td></tr>`;
    }
}

export function initForecastView() {
    const windowChips = document.getElementById('forecast-window-chips');
    const providerChips = document.getElementById('forecast-provider-chips');
    const sortChips = document.getElementById('forecast-sort-chips');
    const stableToggle = document.getElementById('forecast-show-stable-toggle');
    const tbody = document.getElementById('forecast-table-body');

    if (windowChips) {
        windowChips.addEventListener('click', (e) => {
            const btn = e.target.closest('.chip');
            if (!btn) return;
            _filterWindow = btn.dataset.window || '';
            _forecastCache = null;
            loadForecastView();
        });
    }

    if (providerChips) {
        providerChips.addEventListener('click', (e) => {
            const btn = e.target.closest('.chip');
            if (!btn) return;
            _filterProvider = btn.dataset.prov || '';
            _forecastCache = null;
            loadForecastView();
        });
    }

    if (sortChips) {
        sortChips.addEventListener('click', (e) => {
            const btn = e.target.closest('.chip');
            if (!btn) return;
            _sortMode = btn.dataset.sort || 'projected';
            loadForecastView();
        });
    }

    if (stableToggle) {
        stableToggle.addEventListener('click', (e) => {
            if (!e.target.closest('.chip')) return;
            _showStableInChart = !_showStableInChart;
            loadForecastView();
        });
    }

    if (tbody) {
        tbody.addEventListener('click', (e) => {
            const row = e.target.closest('tr.forecast-row');
            if (!row) return;
            _toggleRowExpansion(row);
        });
    }
}
