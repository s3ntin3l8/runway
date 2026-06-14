import { render } from '@testing-library/react';
import type { ReactNode } from 'react';
import { ThemeProvider } from '@/hooks/useTheme';
import type { CumulativeModelBucket } from '@/api/types';

// Capture the option built by the chart instead of rendering real ECharts.
const captured: { option?: Record<string, unknown> } = {};
vi.mock('./EChart', () => ({
  EChart: ({ option }: { option: Record<string, unknown> }) => {
    captured.option = option;
    return <div data-testid="echart" />;
  },
}));

import { CostDonut } from './CostDonut';

function wrapper({ children }: { children: ReactNode }) {
  return <ThemeProvider>{children}</ThemeProvider>;
}

type Series = { data: { name: string; value: number }[] }[];

describe('CostDonut', () => {
  it('builds one slice per key sized by cost_usd, sorted desc and zeros dropped', () => {
    const data: Record<string, CumulativeModelBucket> = {
      small: { cost_usd: 1.5, tokens_input: 999 },
      big: { cost_usd: 12 },
      free: { cost_usd: 0, tokens_input: 100 },
    };
    const { getByTestId } = render(<CostDonut data={data} />, { wrapper });
    expect(getByTestId('echart')).toBeInTheDocument();
    const series = captured.option!.series as Series;
    expect(series[0].data).toEqual([
      { name: 'big', value: 12 },
      { name: 'small', value: 1.5 },
    ]);
  });

  it('produces an empty data set when there is no cost', () => {
    render(<CostDonut data={{ a: { tokens_input: 100 } }} />, { wrapper });
    const series = captured.option!.series as Series;
    expect(series[0].data).toEqual([]);
  });
});
