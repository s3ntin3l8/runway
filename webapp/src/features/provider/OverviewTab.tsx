// Overview: every quota window for the account (gauges), this month's token
// composition + per-model split, and the top sessions.

import { useMemo } from 'react';
import type { CumulativeBucket, FleetEntry } from '@/api/types';
import { Badge } from '@/components/ui/Badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Countdown } from '@/components/ui/Countdown';
import { Gauge } from '@/components/ui/Gauge';
import { Skeleton } from '@/components/ui/Skeleton';
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/Table';
import { TokenDonut } from '@/components/charts/TokenDonut';
import { formatCost, formatDuration, formatPct, formatTokens } from '@/lib/format';
import { cardPct, cardStatus, chipLabel } from '@/lib/quota';
import { useProviderCumulative, useProviderSessions } from './queries';

export function OverviewTab({ entry }: { entry: FleetEntry }) {
  const cumulative = useProviderCumulative(entry.provider_id, entry.account_id);
  const sessions = useProviderSessions(entry.provider_id, entry.account_id);

  const monthBucket = useMemo<CumulativeBucket | null>(() => {
    const data = cumulative.data;
    if (!data) return null;
    const row = data.cumulative.find((c) => c.account_id === entry.account_id);
    const bucket = row?.[data.current_month_key];
    return bucket && typeof bucket !== 'string' ? bucket : null;
  }, [cumulative.data, entry.account_id]);

  const cards = [entry.critical_gauge, ...entry.secondary_limits];

  return (
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
          <CardTitle>Tokens this month</CardTitle>
        </CardHeader>
        <CardContent>
          {cumulative.isPending ? (
            <Skeleton className="h-56 w-full" />
          ) : monthBucket ? (
            <TokenDonut bucket={monthBucket} />
          ) : (
            <p className="py-8 text-center text-xs text-fg-subtle">No usage recorded this month.</p>
          )}
        </CardContent>
      </Card>

      {monthBucket?.by_model && Object.keys(monthBucket.by_model).length > 0 ? (
        <Card className="lg:col-span-2">
          <CardHeader>
            <CardTitle>By model (this month)</CardTitle>
          </CardHeader>
          <Table>
            <THead>
              <TR>
                <TH>Model</TH>
                <TH className="text-right">Messages</TH>
                <TH className="text-right">Tokens</TH>
                <TH className="text-right">Cost</TH>
              </TR>
            </THead>
            <TBody>
              {Object.entries(monthBucket.by_model)
                .sort(([, a], [, b]) => (b.cost_usd ?? 0) - (a.cost_usd ?? 0))
                .map(([model, b]) => (
                  <TR key={model}>
                    <TD className="font-medium">{model}</TD>
                    <TD className="text-right font-mono tabular">{b.msgs ?? 0}</TD>
                    <TD className="text-right font-mono tabular">
                      {formatTokens(
                        (b.tokens_input ?? 0) +
                          (b.tokens_output ?? 0) +
                          (b.tokens_cache_read ?? 0) +
                          (b.tokens_cache_create ?? 0) +
                          (b.tokens_reasoning ?? 0),
                      )}
                    </TD>
                    <TD className="text-right font-mono tabular">{formatCost(b.cost_usd)}</TD>
                  </TR>
                ))}
            </TBody>
          </Table>
        </Card>
      ) : null}

      <Card className="lg:col-span-2">
        <CardHeader>
          <CardTitle>Top sessions (7 days)</CardTitle>
        </CardHeader>
        {sessions.isPending ? (
          <CardContent>
            <Skeleton className="h-24 w-full" />
          </CardContent>
        ) : (sessions.data?.sessions.length ?? 0) === 0 ? (
          <CardContent>
            <p className="py-4 text-center text-xs text-fg-subtle">
              No sessions recorded — session data needs a sidecar feeding events.
            </p>
          </CardContent>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Session</TH>
                <TH>Models</TH>
                <TH className="text-right">Duration</TH>
                <TH className="text-right">Messages</TH>
                <TH className="text-right">Tokens</TH>
                <TH className="text-right">Cost</TH>
              </TR>
            </THead>
            <TBody>
              {sessions.data!.sessions.map((s) => {
                const tokens = (s.by_model ?? []).reduce((sum, m) => sum + (m.tokens_total ?? 0), 0);
                const cost = (s.by_model ?? []).reduce((sum, m) => sum + (m.cost_usd ?? 0), 0);
                return (
                  <TR key={s.session_id}>
                    <TD className="max-w-32 truncate font-mono text-xs" title={s.session_id}>
                      {s.session_id.slice(0, 8)}
                    </TD>
                    <TD>
                      <span className="flex flex-wrap gap-1">
                        {(s.models ?? []).map((m) => (
                          <Badge key={m} variant="neutral">
                            {m}
                          </Badge>
                        ))}
                      </span>
                    </TD>
                    <TD className="text-right font-mono tabular">
                      {s.duration_seconds != null ? formatDuration(s.duration_seconds * 1000) : '—'}
                    </TD>
                    <TD className="text-right font-mono tabular">{s.msgs ?? 0}</TD>
                    <TD className="text-right font-mono tabular">{formatTokens(tokens)}</TD>
                    <TD className="text-right font-mono tabular">{formatCost(cost)}</TD>
                  </TR>
                );
              })}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  );
}
