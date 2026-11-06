import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Freshness, { ago } from './Freshness.jsx';

const NOW = Date.parse('2026-11-06T03:42:30Z'); // 10:42:30 PM New York
const at = (iso) => ({ feed_updated_at: iso });

describe('live data freshness', () => {
  afterEach(() => vi.useRealTimers());

  it('shows Citi Bike time and when the page checked, and refreshes on tap', () => {
    vi.useFakeTimers({ toFake: ['Date', 'setInterval', 'clearInterval'] });
    vi.setSystemTime(NOW);
    const refresh = vi.fn();
    render(<Freshness state={{ status: 'ready', data: at('2026-11-05T22:41:50-05:00'), at: NOW - 20000, refresh }} />);
    expect(screen.getByRole('status').textContent).toContain('Citi Bike data from 10:41 PM · checked 20 s ago');
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(refresh).toHaveBeenCalledOnce();
  });

  it('warns when Citi Bike itself stops updating, and when a refresh fails', () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(NOW);
    const { rerender } = render(<Freshness state={{ status: 'ready', data: at('2026-11-05T22:30:00-05:00'), at: NOW }} />);
    expect(screen.getByRole('status').textContent).toContain("Citi Bike hasn't updated since 10:30 PM.");
    rerender(<Freshness state={{ status: 'error', data: at('2026-11-05T22:39:30-05:00'), at: NOW - 60000 }} />);
    expect(screen.getByRole('status').textContent).toContain("Couldn't refresh. Showing Citi Bike data from 10:39 PM, 3 min ago.");
    expect(screen.getByRole('button', { name: 'Retry' })).toBeTruthy();
  });

  it('counts seconds, then minutes', () => {
    expect([3, 25, 125].map(ago)).toEqual(['just now', '25 s ago', '2 min ago']);
  });
});
