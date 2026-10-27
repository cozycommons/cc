import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import ScanViewer from './ScanViewer';

const mountScan = vi.hoisted(() => vi.fn());
vi.mock('./scanRenderer', () => ({ mountScan }));

describe('ScanViewer', () => {
  beforeEach(() => { mountScan.mockReset(); });

  it('shows loading, enables fit after rendering, and releases the view on unmount', async () => {
    let resolve;
    const view = { fit: vi.fn(), dispose: vi.fn() };
    mountScan.mockReturnValue(new Promise((done) => { resolve = done; }));
    const { unmount } = render(<ScanViewer bytes={new ArrayBuffer(8)} />);
    expect(screen.getByRole('status')).toHaveTextContent('Loading 3D scan');
    await waitFor(() => expect(mountScan).toHaveBeenCalledOnce());
    await act(async () => resolve(view));
    fireEvent.click(screen.getByRole('button', { name: 'Fit scan' }));
    expect(view.fit).toHaveBeenCalledOnce();
    unmount();
    expect(view.dispose).toHaveBeenCalledOnce();
  });

  it('can retry a failed loader without modifying scan bytes', async () => {
    const bytes = new ArrayBuffer(8);
    mountScan.mockRejectedValueOnce(new Error('Invalid model')).mockResolvedValueOnce({ fit: vi.fn(), dispose: vi.fn() });
    render(<ScanViewer bytes={bytes} />);
    expect(await screen.findByRole('alert')).toHaveTextContent('Invalid model');
    fireEvent.click(screen.getByRole('button', { name: 'Retry viewer' }));
    await screen.findByRole('button', { name: 'Fit scan' });
    expect(mountScan.mock.calls.map((call) => call[1])).toEqual([bytes, bytes]);
  });

  it('disposes a renderer that finishes loading after the viewer is closed', async () => {
    let resolve;
    const view = { fit: vi.fn(), dispose: vi.fn() };
    mountScan.mockReturnValue(new Promise((done) => { resolve = done; }));
    const { unmount } = render(<ScanViewer bytes={new ArrayBuffer(8)} />);
    await waitFor(() => expect(mountScan).toHaveBeenCalledOnce());
    unmount();
    await act(async () => resolve(view));
    expect(view.dispose).toHaveBeenCalledOnce();
  });
});
