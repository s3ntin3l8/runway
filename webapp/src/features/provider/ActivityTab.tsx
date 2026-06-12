// Activity: "what have I been doing?" — per-day token volume, the token
// composition this month, the hour×weekday heatmap, top sessions (with
// subagent splits) and the recent event tail.

import { useMemo } from 'react';
import type { CumulativeBucket } from '@/api/types';
import { Badge } from '@/components/ui/Badge';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Skeleton } from '@/components/ui/Skeleton';
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/Table';
import { TokenDonut } from '@/components/charts/TokenDonut';
import { UsageHeatmap } from '@/components/charts/UsageHeatmap';
import { formatCost, formatDuration, formatTokens } from '@/lib/format';
import { formatLocalDateTime, getUserTz } from '@/lib/tz';
import { ProviderTrendCard } from './ProviderTrendCard';
import {
  useProviderCumulative,
  useProviderEvents,
  useProviderHeatmap,
  useProviderSessions,
} from './queries';

export function ActivityTab({ providerId, accountId }: { providerId: string; accountId: string }) {
  const heatmap = useProviderHeatmap(providerId, accountId, getUserTz());
  const events = useProviderEvents(providerId, accountId);
  const sessions = useProviderSessions(providerId, accountId);
  const cumulative = useProviderCumulative(providerId, accountId);

  const monthBucket = useMemo<CumulativeBucket | null>(() => {
    const data = cumulative.data;
    if (!data) return null;
    const row = data.cumulative.find((c) => c.account_id === accountId);
    const bucket = row?.[data.current_month_key];
    return bucket && typeof bucket !== 'string' ? bucket : null;
  }, [cumulative.data, accountId]);

  return (
    <div className="flex flex-col gap-4">
      <ProviderTrendCard
        providerId={providerId}
        accountId={accountId}
        metric="tokens"
        title="Tokens per day"
      />

      <div className="grid gap-4 lg:grid-cols-2">
        <Card>
          <CardHeader>
            <CardTitle>Token composition (month)</CardTitle>
          </CardHeader>
          <CardContent>
            {cumulative.isPending ? (
              <Skeleton className="h-56 w-full" />
            ) : monthBucket ? (
              <TokenDonut bucket={monthBucket} />
            ) : (
              <p className="py-8 text-center text-xs text-fg-subtle">
                No usage recorded this month.
              </p>
            )}
          </CardContent>
        </Card>

        <Card>
          <CardHeader>
            <CardTitle>Activity by hour (14 days)</CardTitle>
            {heatmap.data ? (
              <span className="text-[11px] text-fg-subtle">{heatmap.data.tz}</span>
            ) : null}
          </CardHeader>
          <CardContent>
            {heatmap.isPending ? (
              <Skeleton className="h-56 w-full" />
            ) : heatmap.data && heatmap.data.cells.some((c) => c.tokens > 0) ? (
              <UsageHeatmap cells={heatmap.data.cells} />
            ) : (
              <p className="py-8 text-center text-xs text-fg-subtle">
                No event activity in the last 14 days.
              </p>
            )}
          </CardContent>
        </Card>
      </div>

      <Card>
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
                <TH className="hidden lg:table-cell">Agents</TH>
                <TH className="text-right">Duration</TH>
                <TH className="text-right">Messages</TH>
                <TH className="text-right">Tokens</TH>
                <TH className="text-right">Cost</TH>
              </TR>
            </THead>
            <TBody>
              {sessions.data!.sessions.map((s) => {
                const tokens =
                  s.tokens_total ??
                  (s.by_model ?? []).reduce((sum, m) => sum + (m.tokens_total ?? 0), 0);
                const cost =
                  s.cost_usd ?? (s.by_model ?? []).reduce((sum, m) => sum + (m.cost_usd ?? 0), 0);
                const agents = (s.subagents ?? [])
                  .map((a) => `${a.subagent_type}·${a.turns ?? 0}`)
                  .join(' ');
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
                    <TD className="hidden font-mono text-xs text-fg-muted lg:table-cell">
                      {agents || '—'}
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

      <Card>
        <CardHeader>
          <CardTitle>Recent events</CardTitle>
          {events.data ? (
            <span className="text-[11px] text-fg-subtle">
              {events.data.events.length} of {events.data.total}
            </span>
          ) : null}
        </CardHeader>
        {events.isPending ? (
          <CardContent>
            <Skeleton className="h-32 w-full" />
          </CardContent>
        ) : (events.data?.events.length ?? 0) === 0 ? (
          <CardContent>
            <p className="py-4 text-center text-xs text-fg-subtle">
              No events — per-message events arrive via sidecar ingest.
            </p>
          </CardContent>
        ) : (
          <Table>
            <THead>
              <TR>
                <TH>Time</TH>
                <TH>Model</TH>
                <TH className="hidden md:table-cell">Sidecar</TH>
                <TH className="text-right">In</TH>
                <TH className="text-right">Out</TH>
                <TH className="hidden text-right sm:table-cell">Cache</TH>
                <TH className="text-right">Cost</TH>
              </TR>
            </THead>
            <TBody>
              {events.data!.events.map((e) => (
                <TR key={e.event_id ?? e.id}>
                  <TD className="font-mono text-xs whitespace-nowrap tabular">
                    {formatLocalDateTime(e.ts, {
                      month: 'short',
                      day: 'numeric',
                      hour: '2-digit',
                      minute: '2-digit',
                    })}
                  </TD>
                  <TD>
                    {e.kind === 'error' ? (
                      <Badge variant="critical">error</Badge>
                    ) : (
                      <span className="text-xs">{e.model_id ?? '—'}</span>
                    )}
                  </TD>
                  <TD className="hidden text-xs text-fg-muted md:table-cell">
                    {e.sidecar_id ?? '—'}
                  </TD>
                  <TD className="text-right font-mono text-xs tabular">
                    {formatTokens(e.tokens_input ?? 0)}
                  </TD>
                  <TD className="text-right font-mono text-xs tabular">
                    {formatTokens(e.tokens_output ?? 0)}
                  </TD>
                  <TD className="hidden text-right font-mono text-xs tabular sm:table-cell">
                    {formatTokens((e.tokens_cache_read ?? 0) + (e.tokens_cache_create ?? 0))}
                  </TD>
                  <TD className="text-right font-mono text-xs tabular">{formatCost(e.cost_usd)}</TD>
                </TR>
              ))}
            </TBody>
          </Table>
        )}
      </Card>
    </div>
  );
}
