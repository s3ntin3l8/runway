// Cost: MTD spend + EOM projection for this provider, per-model and
// per-sidecar splits from the cumulative month bucket.

import { useMemo } from 'react';
import { useQuery } from '@tanstack/react-query';
import { fetchCostForecast } from '@/api/endpoints';
import type { CumulativeBucket } from '@/api/types';
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/Card';
import { Skeleton } from '@/components/ui/Skeleton';
import { Table, TBody, TD, TH, THead, TR } from '@/components/ui/Table';
import { formatCost, formatTokens } from '@/lib/format';
import { useProviderCumulative } from './queries';

export function CostTab({ providerId, accountId }: { providerId: string; accountId: string }) {
  const cost = useQuery({
    queryKey: ['usage', 'cost-forecast', providerId, accountId],
    queryFn: () => fetchCostForecast({ provider_id: providerId, account_id: accountId }),
    refetchInterval: 120_000,
  });
  const cumulative = useProviderCumulative(providerId, accountId);

  const monthBucket = useMemo<CumulativeBucket | null>(() => {
    const data = cumulative.data;
    if (!data) return null;
    const row = data.cumulative.find((c) => c.account_id === accountId);
    const bucket = row?.[data.current_month_key];
    return bucket && typeof bucket !== 'string' ? bucket : null;
  }, [cumulative.data, accountId]);

  const lifetime = useMemo<CumulativeBucket | null>(() => {
    const row = cumulative.data?.cumulative.find((c) => c.account_id === accountId);
    return row?.lifetime ?? null;
  }, [cumulative.data, accountId]);

  const stats = [
    { label: 'Spend (MTD)', value: formatCost(cost.data?.current_month_to_date ?? null) },
    {
      label: 'Projected EOM',
      value: formatCost(cost.data?.projected_eom ?? null),
      hint: cost.data ? `${cost.data.days_remaining}d left` : undefined,
    },
    { label: 'Daily burn (7d)', value: formatCost(cost.data?.daily_burn_avg_7d ?? null) },
    { label: 'Lifetime', value: formatCost(lifetime?.cost_usd ?? null) },
  ];

  return (
    <div className="flex flex-col gap-4">
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
        {stats.map((stat) => (
          <Card key={stat.label} className="px-4 py-3">
            <p className="text-[11px] font-medium text-fg-subtle">{stat.label}</p>
            {cost.isPending || cumulative.isPending ? (
              <Skeleton className="mt-1.5 h-6 w-20" />
            ) : (
              <div className="mt-0.5 flex items-baseline gap-2">
                <span className="font-mono text-lg font-semibold tabular">{stat.value}</span>
                {stat.hint ? <span className="text-[11px] text-fg-subtle">{stat.hint}</span> : null}
              </div>
            )}
          </Card>
        ))}
      </div>

      <SplitTable
        title="Cost by model (this month)"
        split={monthBucket?.by_model}
        loading={cumulative.isPending}
        nameHeader="Model"
      />
      <SplitTable
        title="Cost by sidecar (this month)"
        split={monthBucket?.by_sidecar}
        loading={cumulative.isPending}
        nameHeader="Sidecar"
      />
    </div>
  );
}

function SplitTable({
  title,
  split,
  loading,
  nameHeader,
}: {
  title: string;
  split: CumulativeBucket['by_model'] | undefined | null;
  loading: boolean;
  nameHeader: string;
}) {
  const rows = Object.entries(split ?? {}).sort(
    ([, a], [, b]) => (b.cost_usd ?? 0) - (a.cost_usd ?? 0),
  );
  return (
    <Card>
      <CardHeader>
        <CardTitle>{title}</CardTitle>
      </CardHeader>
      {loading ? (
        <CardContent>
          <Skeleton className="h-24 w-full" />
        </CardContent>
      ) : rows.length === 0 ? (
        <CardContent>
          <p className="py-4 text-center text-xs text-fg-subtle">No cost data this month.</p>
        </CardContent>
      ) : (
        <Table>
          <THead>
            <TR>
              <TH>{nameHeader}</TH>
              <TH className="text-right">Messages</TH>
              <TH className="text-right">Tokens</TH>
              <TH className="text-right">Cost</TH>
            </TR>
          </THead>
          <TBody>
            {rows.map(([name, b]) => (
              <TR key={name}>
                <TD className="font-medium">{name}</TD>
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
      )}
    </Card>
  );
}
