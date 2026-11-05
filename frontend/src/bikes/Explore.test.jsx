import React from 'react';
import { fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Explore from './Explore.jsx';

const rates = (weekday17, weekend17) => {
  const r = Array(48).fill(50);
  r[17] = weekday17;
  r[24 + 17] = weekend17;
  return r;
};
const DATA = {
  window: ['2025-11', '2026-10'],
  stations: {
    id: ['6230.04', '7932.01'],
    name: ['W 33 St & 7 Ave', 'E 134 St & Willis Ave'],
    lat: [40.7502, 40.8102], lng: [-73.9916, -73.9235],
    rates: [rates(12000, 3000), rates(4, 4)],
  },
  history: { month: ['2025-12', '2026-01', '2026-02'], nyc: [1000000, 900000, 1200000], jc: [50000, 40000, 60000] },
};

describe('explore', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

  it('ranks docks for the chosen hour and day type, and opens a station', async () => {
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date(2026, 6, 15, 17, 30)); // a Wednesday, 5:30 PM local
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => DATA })));
    render(<Explore />);

    const table = await screen.findByRole('table', { name: 'Busiest docks at 5 PM' });
    const first = within(table).getAllByRole('row')[1];
    expect(first.textContent).toBe('W 33 St & 7 Ave120.01 min');

    fireEvent.click(screen.getByRole('tab', { name: 'Weekend' }));
    expect(within(table).getAllByRole('row')[1].textContent).toBe('W 33 St & 7 Ave30.02 min');

    fireEvent.change(screen.getByRole('slider', { name: 'Hour of day' }), { target: { value: '3' } });
    expect(screen.getByRole('table', { name: 'Busiest docks at 3 AM' })).toBeTruthy();

    fireEvent.click(within(table).getByRole('button', { name: 'E 134 St & Willis Ave' }));
    expect(screen.getByRole('heading', { name: 'E 134 St & Willis Ave' })).toBeTruthy();
    expect(screen.getByText(/a dock usually opens\s+in 120 min/)).toBeTruthy();
    expect(screen.getByText('3.3M trips since 2025-12.')).toBeTruthy();
  });
});
