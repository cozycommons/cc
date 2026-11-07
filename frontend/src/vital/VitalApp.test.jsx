import React from 'react';
import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import VitalApp, { newYorkNow, quietestAhead, verdict } from './VitalApp.jsx';

vi.mock('../components/SiteHeader.jsx', () => ({ default: () => null }));
vi.mock('../api.js', () => ({ getUrl: () => 'https://api.test' }));

const friday = Array(24).fill(50);
friday[19] = 210; friday[20] = 155; friday[21] = 92; friday[22] = 31; friday[23] = 14;
const WEEK = { from: '2025-11-06', to: '2026-11-06', samples: 13542, hours: Array.from({ length: 7 }, () => friday) };

describe('VITAL', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('reads weekday and hour from the API timestamp', () => {
    expect(newYorkNow('2026-11-06T20:05:00-05:00')).toEqual({ day: 4, hour: 20 });
    expect(newYorkNow('2026-11-09T07:59:00-05:00')).toEqual({ day: 0, hour: 7 });
  });

  it('compares with the typical hour, but not when the gym is barely open', () => {
    expect([verdict(191, 155), verdict(160, 155), verdict(100, 155), verdict(3, 1)])
      .toEqual(['Busier than usual', 'About usual', 'Quieter than usual', null]);
  });

  it('suggests the quietest open hour still ahead, if it beats now', () => {
    expect(quietestAhead(friday, 20, 191)).toEqual({ hour: 22, people: 31 });
    expect(quietestAhead(friday, 20, 20)).toBeNull();
    expect(quietestAhead(friday, 23, 191)).toBeNull();
  });

  it('shows the live count against the typical hour', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url) => ({
      ok: true,
      json: async () => (url.endsWith('/now') ? { people: 191, at: '2026-11-06T20:05:00-05:00', typical: 155 } : WEEK),
    })));
    render(<VitalApp />);
    expect((await screen.findByText('people now')).textContent).toBe('191 people now');
    expect(screen.getByText('Busier than usual')).toBeTruthy();
    expect(screen.getByText('Typical Fri 8 PM: 155')).toBeTruthy();
    expect((await screen.findByText(/Quietest later today/)).textContent).toBe('Quietest later today: 10 PM, about 31');
    expect(screen.getByRole('tab', { name: 'Fri', selected: true })).toBeTruthy();
  });

  it('says so when the count is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn(async (url) => (url.endsWith('/now')
      ? { ok: false, json: async () => ({ detail: 'The VITAL headcount is unavailable right now.' }) }
      : { ok: true, json: async () => WEEK })));
    render(<VitalApp />);
    expect((await screen.findByRole('alert')).textContent).toBe('The VITAL headcount is unavailable right now.');
  });
});
