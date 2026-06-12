// Provider-detail data hooks, parametrized by (provider_id, account_id).

import { useQuery } from '@tanstack/react-query';
import {
  fetchCumulative,
  fetchDebugRaw,
  fetchEvents,
  fetchForecast,
  fetchHeatmap,
  fetchSessions,
  fetchWindowHistory,
} from '@/api/endpoints';

export const useProviderForecast = (providerId: string, accountId: string) =>
  useQuery({
    queryKey: ['usage', 'forecast', providerId, accountId, 'series'],
    queryFn: () =>
      fetchForecast({ provider_id: providerId, account_id: accountId, include_series: true }),
    refetchInterval: 60_000,
  });

export const useProviderCumulative = (providerId: string, accountId: string) =>
  useQuery({
    queryKey: ['usage', 'cumulative', providerId, accountId],
    queryFn: () => fetchCumulative({ provider_id: providerId, account_id: accountId }),
    refetchInterval: 120_000,
  });

export const useProviderHeatmap = (providerId: string, accountId: string, tz: string) =>
  useQuery({
    queryKey: ['usage', 'heatmap', providerId, accountId, tz],
    queryFn: () => fetchHeatmap({ provider_id: providerId, account_id: accountId, days: 14, tz }),
    refetchInterval: 300_000,
  });

export const useProviderSessions = (providerId: string, accountId: string) =>
  useQuery({
    queryKey: ['usage', 'sessions', providerId, accountId],
    queryFn: () =>
      fetchSessions({ provider_id: providerId, account_id: accountId, limit: 10, sort_by: 'tokens' }),
    refetchInterval: 120_000,
  });

export const useProviderEvents = (providerId: string, accountId: string) =>
  useQuery({
    queryKey: ['usage', 'events', providerId, accountId],
    queryFn: () => fetchEvents({ provider_id: providerId, account_id: accountId, limit: 50 }),
    refetchInterval: 60_000,
  });

export const useWindowHistory = (providerId: string, accountId: string, windowType: string) =>
  useQuery({
    queryKey: ['usage', 'window-history', providerId, accountId, windowType],
    queryFn: () =>
      fetchWindowHistory({
        provider_id: providerId,
        account_id: accountId,
        window_type: windowType,
        limit: 12,
      }),
    enabled: windowType !== 'unknown' && windowType !== '',
  });

export const useDebugRaw = (providerId: string, enabled: boolean) =>
  useQuery({
    queryKey: ['system', 'debug-raw', providerId],
    queryFn: () => fetchDebugRaw(providerId),
    enabled,
    // 10/min rate limit + live upstream calls: fetch once per explicit ask
    staleTime: Infinity,
    retry: false,
  });
