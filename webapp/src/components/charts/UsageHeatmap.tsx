// Hour-of-day × day-of-week token heatmap (7×24 grid from /usage/heatmap).
// dow follows the SQLite convention: 0=Sunday … 6=Saturday.

import { useMemo } from 'react';
import type { HeatmapCell } from '@/api/types';
import { formatTokens } from '@/lib/format';
import { EChart } from './EChart';
import { baseTooltip, useChartTokens } from './theme';

const DAYS = ['Sun', 'Mon', 'Tue', 'Wed', 'Thu', 'Fri', 'Sat'];

export function UsageHeatmap({ cells, className }: { cells: HeatmapCell[]; className?: string }) {
  const t = useChartTokens();
  const option = useMemo(() => {
    const data = cells.map((c) => [c.hour, c.dow, c.tokens]);
    const max = Math.max(1, ...cells.map((c) => c.tokens));
    return {
      tooltip: {
        ...baseTooltip(t),
        formatter: (p: { value: [number, number, number] }) =>
          `${DAYS[p.value[1]]} ${String(p.value[0]).padStart(2, '0')}:00 — ${formatTokens(p.value[2])} tokens`,
      },
      grid: { left: 40, right: 8, top: 8, bottom: 44 },
      xAxis: {
        type: 'category',
        data: Array.from({ length: 24 }, (_, h) => String(h)),
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: {
          color: t.axis,
          fontSize: 10,
          fontFamily: t.fontFamily,
          interval: 2,
        },
        splitArea: { show: false },
      },
      yAxis: {
        type: 'category',
        data: DAYS,
        axisLine: { show: false },
        axisTick: { show: false },
        axisLabel: { color: t.axis, fontSize: 10, fontFamily: t.fontFamily },
      },
      visualMap: {
        min: 0,
        max,
        calculable: false,
        orient: 'horizontal',
        left: 'center',
        bottom: 0,
        itemHeight: 80,
        textStyle: { color: t.axis, fontSize: 10, fontFamily: t.fontFamily },
        formatter: (v: number) => formatTokens(v),
        // Faint-accent → accent ramp. Using --accent-muted (a low-alpha tint
        // of the accent) keeps low cells readable in BOTH themes; the old
        // --chart-grid floor rendered near-black on the light surface.
        inRange: { color: [t.accentMuted, t.accent] },
      },
      series: [
        {
          type: 'heatmap',
          data,
          itemStyle: { borderColor: t.surface, borderWidth: 1.5, borderRadius: 2 },
          emphasis: { itemStyle: { borderColor: t.fg } },
        },
      ],
    };
  }, [cells, t]);

  return <EChart option={option} className={className ?? 'h-64'} />;
}
