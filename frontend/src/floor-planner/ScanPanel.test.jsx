import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ScanPanel from './ScanPanel';

const scanRequest = vi.hoisted(() => vi.fn());
vi.mock('./scanApi', () => ({ scanRequest, MAX_SCAN_BYTES: 50 * 1024 * 1024 }));
vi.mock('./ScanViewer', () => ({ default: () => <div>Rendered scan</div> }));
const props = { supabase: {}, userId: 'owner', planId: 'plan-1' };

describe('ScanPanel', () => {
  beforeEach(() => { scanRequest.mockReset(); });

  it('uploads a private scan and displays the saved model', async () => {
    scanRequest.mockResolvedValueOnce({ scan: null })
      .mockResolvedValueOnce({ scan: { id: 'scan-1', filename: 'room.usdz', byte_size: 4 } })
      .mockResolvedValueOnce(new ArrayBuffer(4));
    render(<ScanPanel {...props} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Upload USDZ' })).toBeEnabled());
    expect(screen.getByText(/excluded from the public gallery/)).toBeInTheDocument();
    const file = new File(['data'], 'room.usdz');
    fireEvent.change(screen.getByLabelText('Choose USDZ scan'), { target: { files: [file] } });
    expect(await screen.findByText('Rendered scan')).toBeInTheDocument();
    expect(scanRequest.mock.calls[1][3]).toMatchObject({ method: 'PUT', file, scanId: undefined });
    expect(screen.getByText('room.usdz')).toBeInTheDocument();
  });

  it('rejects the wrong file type before starting an upload', async () => {
    scanRequest.mockResolvedValue({ scan: null });
    render(<ScanPanel {...props} />);
    await waitFor(() => expect(screen.getByRole('button', { name: 'Upload USDZ' })).toBeEnabled());
    fireEvent.change(screen.getByLabelText('Choose USDZ scan'), { target: { files: [new File(['data'], 'room.txt')] } });
    expect(screen.getByRole('alert')).toHaveTextContent('Choose a USDZ file');
    expect(scanRequest).toHaveBeenCalledOnce();
  });

  it('retains the old attachment when replacement fails', async () => {
    scanRequest.mockResolvedValueOnce({ scan: { id: 'original', filename: 'original.usdz' } })
      .mockResolvedValueOnce(new ArrayBuffer(4)).mockRejectedValueOnce(new Error('Storage unavailable'));
    render(<ScanPanel {...props} />);
    await screen.findByText('Rendered scan');
    fireEvent.change(screen.getByLabelText('Choose USDZ scan'), { target: { files: [new File(['data'], 'new.usdz')] } });
    expect(await screen.findByRole('alert')).toHaveTextContent('Storage unavailable');
    expect(screen.getByText('original.usdz')).toBeInTheDocument();
    expect(screen.getByText('Rendered scan')).toBeInTheDocument();
    expect(scanRequest.mock.calls[2][3]).toMatchObject({ method: 'PUT', scanId: 'original' });
  });

  it('clears the model after a permission denial and can retry a failed download', async () => {
    const failure = new Error('Scan access changed');
    failure.status = 404;
    scanRequest.mockResolvedValueOnce({ scan: { id: 'scan-1', filename: 'room.usdz' } })
      .mockRejectedValueOnce(new Error('Download unavailable'));
    render(<ScanPanel {...props} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Download unavailable');
    expect(screen.queryByText('Rendered scan')).not.toBeInTheDocument();
    scanRequest.mockRejectedValue(failure);
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.queryByText('room.usdz')).not.toBeInTheDocument());
    expect(screen.queryByText('Rendered scan')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('Scan access changed');
  });
});
