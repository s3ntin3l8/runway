import { describe, expect, it } from 'vitest';
import type { CumulativeModelBucket } from '@/api/types';
import { hasTokenData, sumTokens } from './cumulative';

const bucket = (o: Partial<CumulativeModelBucket> = {}): CumulativeModelBucket => o;

describe('sumTokens', () => {
  it('returns 0 for null/undefined buckets', () => {
    expect(sumTokens(null)).toBe(0);
    expect(sumTokens(undefined)).toBe(0);
  });

  it('returns 0 for a present-but-empty bucket', () => {
    expect(sumTokens(bucket())).toBe(0);
  });

  it('sums the five token components', () => {
    expect(
      sumTokens(
        bucket({
          tokens_input: 100,
          tokens_output: 50,
          tokens_cache_read: 700,
          tokens_cache_create: 140,
          tokens_reasoning: 10,
        }),
      ),
    ).toBe(1000);
  });

  it('treats missing fields as zero (not NaN)', () => {
    expect(sumTokens(bucket({ tokens_input: 5 }))).toBe(5);
  });

  it('excludes cache components when excludeCache is true', () => {
    expect(
      sumTokens(
        bucket({
          tokens_input: 100,
          tokens_output: 50,
          tokens_cache_read: 700,
          tokens_cache_create: 140,
          tokens_reasoning: 10,
        }),
        true,
      ),
    ).toBe(160);
  });
});

describe('hasTokenData', () => {
  it('is false for null/undefined/empty buckets', () => {
    expect(hasTokenData(null)).toBe(false);
    expect(hasTokenData(undefined)).toBe(false);
    expect(hasTokenData(bucket())).toBe(false);
  });

  it('is true when any component is non-zero', () => {
    expect(hasTokenData(bucket({ tokens_reasoning: 1 }))).toBe(true);
    expect(hasTokenData(bucket({ tokens_cache_read: 1 }))).toBe(true);
  });
});
