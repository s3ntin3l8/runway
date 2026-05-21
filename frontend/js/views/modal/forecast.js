/**
 * Forecast pane builder for the provider detail modal.
 *
 * Renders per-pool quota trajectory mini-charts using the /api/v1/usage/forecast
 * endpoint (with include_series=true).
 */

import { escapeHTML as _esc } from '../../utils/html.js';
import { renderTrajectoryChart, formatTrajectoryHeader, STATUS_COLOR as TRAJ_STATUS_COLOR } from '../../components/forecast-trajectory.js';

// Track ECharts instances for disposal
const _trajectoryCharts = [];

/** Dispose all trajectory ECharts instances. Call before re-rendering or closing modal. */
export function disposeTrajectoryCharts() {
    for (const c of _trajectoryCharts) {
        try { c.dispose(); } catch (_) {}
    }
    _trajectoryCharts.length = 0;
}

/** Build the forecast pane HTML. forecastEntries is the array from /forecast?include_series=true. */
export function buildForecastPane(forecastEntries) {
    if (!forecastEntries?.length) {
        return '<div class="pm-empty">No forecast data available.</div>';
    }

    const poolsHtml = forecastEntries.map((fe, i) => {
        const { label, detail } = formatTrajectoryHeader(fe);
        const color = TRAJ_STATUS_COLOR[fe.status] || 'var(--text-dim)';
        const statusLabel = (fe.status || '').toUpperCase();
        return `<div class="m-traj-pool">
            <div class="m-traj-head">
                <span>${_esc(label)}</span>
                <span style="color:${color};font-size:10px;font-weight:600;">${statusLabel}</span>
                ${detail ? `<span style="color:var(--text-dim);font-size:9px;">${_esc(detail)}</span>` : ''}
            </div>
            <div class="m-traj-chart" id="pm-traj-${i}" style="height:140px;"></div>
        </div>`;
    }).join('');

    return `
    <div class="m-block" id="pm-trajectory-wrap">
        <div class="head">
            <h4>Quota trajectories</h4>
            <span class="meta">${forecastEntries.length} pool${forecastEntries.length !== 1 ? 's' : ''}</span>
        </div>
        ${poolsHtml}
    </div>`;
}

/** Mount ECharts into the containers created by buildForecastPane. */
export async function wireForecastPane(forecastEntries) {
    disposeTrajectoryCharts();
    if (!forecastEntries?.length) return;
    for (let i = 0; i < forecastEntries.length; i++) {
        const el = document.getElementById(`pm-traj-${i}`);
        if (!el) continue;
        const entry = forecastEntries[i];
        const chart = await renderTrajectoryChart(el, entry.series || [], {
            windowStart: entry.window_start,
            resetAt: entry.reset_at,
            projectedPct: entry.projected_pct,
            projectedLimitHitAt: entry.projected_limit_hit_at,
        });
        if (chart) _trajectoryCharts.push(chart);
    }
}
