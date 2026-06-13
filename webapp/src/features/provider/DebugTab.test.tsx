import { screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { renderWithProviders } from '@/test/utils';
import { DebugTab } from './DebugTab';
import * as api from '@/api/endpoints';

vi.mock('@/api/endpoints');

describe('DebugTab', () => {
  beforeEach(() => vi.clearAllMocks());

  it('shows the capture prompt and does not auto-fetch', () => {
    renderWithProviders(<DebugTab providerId="anthropic" active />);
    expect(screen.getByText(/capture raw collector output/i)).toBeInTheDocument();
    expect(api.fetchDebugRaw).not.toHaveBeenCalled();
  });

  it('runs the capture and renders the raw JSON', async () => {
    vi.mocked(api.fetchDebugRaw).mockResolvedValue({ provider: 'anthropic', ok: true } as never);
    renderWithProviders(<DebugTab providerId="anthropic" active />);

    await userEvent.click(screen.getByRole('button', { name: /run capture/i }));
    expect(await screen.findByText('Raw collector exchange')).toBeInTheDocument();
    await waitFor(() => expect(api.fetchDebugRaw).toHaveBeenCalledWith('anthropic'));
  });

  it('shows a failure state with retry on error', async () => {
    vi.mocked(api.fetchDebugRaw).mockRejectedValue(new Error('rate limited'));
    renderWithProviders(<DebugTab providerId="anthropic" active />);

    await userEvent.click(screen.getByRole('button', { name: /run capture/i }));
    expect(await screen.findByText(/capture failed/i)).toBeInTheDocument();
    expect(screen.getByText(/rate limited/i)).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /retry/i })).toBeInTheDocument();
  });
});
