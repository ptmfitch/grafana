import { screen, waitFor } from '@testing-library/react';
import { render } from 'test/test-utils';

import { getBackendSrv } from '@grafana/runtime';

import { StatusHud } from './StatusHud';

jest.mock('@grafana/runtime', () => ({
  ...jest.requireActual('@grafana/runtime'),
  getBackendSrv: jest.fn(),
}));

const mockGet = jest.fn();

describe('StatusHud', () => {
  beforeEach(() => {
    jest.clearAllMocks();
    jest.mocked(getBackendSrv).mockReturnValue({ get: mockGet } as unknown as ReturnType<typeof getBackendSrv>);
  });

  it('shows a green lit indicator and OK when /api/health succeeds', async () => {
    mockGet.mockResolvedValue({ database: 'ok' });

    render(<StatusHud />);

    await waitFor(() => {
      expect(screen.getByTestId('status-hud')).toHaveAttribute('data-status', 'ok');
    });

    expect(screen.getByText('OK')).toBeInTheDocument();
    expect(mockGet).toHaveBeenCalledWith('/api/health', undefined, undefined, {
      showErrorAlert: false,
      showSuccessAlert: false,
    });
  });

  it('shows a red indicator without OK when /api/health fails', async () => {
    mockGet.mockRejectedValue(new Error('Service Unavailable'));

    render(<StatusHud />);

    await waitFor(() => {
      expect(screen.getByTestId('status-hud')).toHaveAttribute('data-status', 'error');
    });

    expect(screen.queryByText('OK')).not.toBeInTheDocument();
  });
});
