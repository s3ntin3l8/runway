// Overview: "how am I doing right now?" — a KPI strip, any anomaly/error
// alerts, the quota-window gauges, and a compact fill trajectory for the
// critical window so the answer to "am I on pace?" is visible without a tab
// switch.

import { useMemo } from 'react';
import type { FleetEntry } from '@/api/types';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Countdown } from '@/components/ui/Countdown';
import { Gauge } from '@/components/ui/Gauge';
import { Skeleton } from '@/components/ui/Skeleton';
import { TrajectoryChart } from '@/components/charts/TrajectoryChart';
import { formatPct } from '@/lib/format';
import { cardPct, cardStatus, chipLabel } from '@/lib/quota';
import { ProviderAlerts } from './ProviderAlerts';
import { ProviderKpis } from './ProviderKpis';
import { useProviderForecast } from './queries';

export function OverviewTab({ entry }: { entry: FleetEntry }) {
  const forecast = useProviderForecast(entry.provider_id, entry.account_id);
  const cards = [entry.critical_gauge, ...entry.secondary_limits];

  // Trajectory for the window we treat as critical (fall back to the first).
  const criticalForecast = useMemo(() => {
    const fs = forecast.data?.forecasts ?? [];
    return fs.find((f) => f.window_type === entry.critical_gauge.window_type) ?? fs[0] ?? null;
  }, [forecast.data, entry.critical_gauge.window_type]);

  return (
    <div className="flex flex-col gap-4">
      <ProviderKpis entry={entry} />
      <ProviderAlerts providerId={entry.provider_id} accountId={entry.account_id} />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Quota windows</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-col gap-4">
            {cards.map((card, i) => (
              <div key={`${card.service_name}-${card.window_type}-${i}`}>
                <div className="flex items-baseline justify-between gap-2">
                  <span className="text-[13px] font-medium">{chipLabel(card, cards)}</span>
                  <span className="font-mono text-[13px] font-semibold tabular">
                    {cardPct(card) != null ? formatPct(cardPct(card)) : (card.remaining ?? '—')}
                  </span>
                </div>
                <Gauge pct={cardPct(card)} status={cardStatus(card)} className="mt-1.5" />
                <div className="mt-1 flex items-center justify-between text-[11px] text-fg-subtle">
                  <Countdown until={card.reset_at} className="text-[11px]" />
                  <span>{card.detail || card.window_type}</span>
                </div>
              </div>
            ))}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Current window</CardTitle>
            {criticalForecast ? (
              <span className="text-[11px] text-fg-subtle">
                projected {formatPct(criticalForecast.projected_pct)} at reset
              </span>
            ) : null}
          </CardHeader>
          <CardContent>
            {forecast.isPending ? (
              <Skeleton className="h-44 w-full" />
            ) : criticalForecast ? (
              <TrajectoryChart forecast={criticalForecast} className="h-44 w-full" />
            ) : (
              <p className="py-12 text-center text-xs text-fg-subtle">No trajectory yet.</p>
            )}
          </CardContent>
        </Card>
      </div>
    </div>
  );
}
