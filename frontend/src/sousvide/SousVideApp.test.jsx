import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SousVideApp, { fmtF, fmtInches, fmtMinutes, forgetPlans, shade } from './SousVideApp.jsx';

vi.mock('../components/SiteHeader.jsx', () => ({ default: () => null }));
vi.mock('../api.js', () => ({ getUrl: () => 'https://api.test' }));

const row = (strategy, bath_c, minutes, extra = {}) => ({
  strategy, bath_c, minutes, switch_minutes: null, core_peak_c: 54, bath_overcooked_mm: 0, overcooked_mm: 4.5,
  overcooked_pct: 45, gray_mm: 2.4, saved_minutes: 56.5 - minutes, extra_overcooked_mm: 0, ...extra,
});
const trace = (end) => [0, end / 2, end].map((min, i) => ({ min, phase: 'bath', core: [5, 40, 54][i], mid: 50, surface: 55 }));
const profile = [{ depth_mm: 0, peak_c: 100 }, { depth_mm: 5, peak_c: 57 }, { depth_mm: 10, peak_c: 54 }];
const PLAN = {
  classic: row('classic', 54.5, 56.5),
  hot_and_pull: row('hot_and_pull', 57.5, 18.8),
  hot_then_drop: row('hot_then_drop', 57.5, 40, { switch_minutes: 38 }),
  sweep: [row('hot_and_pull', 54.5, 30), row('hot_and_pull', 57.5, 18.8)],
  trace: { classic: trace(60), hot_and_pull: trace(25), hot_then_drop: trace(45) },
  profile: { classic: profile, hot_and_pull: profile, hot_then_drop: profile },
  warnings: [],
};

describe('Sous vide', () => {
  afterEach(() => { vi.unstubAllGlobals(); forgetPlans(); });

  it('formats temperatures, thickness and durations for a US kitchen', () => {
    expect([fmtF(54.5), fmtInches(38), fmtMinutes(18.8), fmtMinutes(152)]).toEqual(['130°F', '1.5″', '19 min', '2 h 32']);
  });

  it('shades meat from red to gray to crust as its peak temperature rises', () => {
    expect(shade(54)).not.toBe(shade(70));
    expect(shade(30)).toBe(shade(40));
    expect(shade(300)).toBe('rgb(84,52,34)');
  });

  it('compares the three methods for the chosen steak', async () => {
    const fetch = vi.fn(async () => ({ ok: true, json: async () => PLAN }));
    vi.stubGlobal('fetch', fetch);
    // The plan suspends; React 19 wants that render awaited inside act.
    await act(async () => { render(<SousVideApp />); });
    const pull = await screen.findByRole('article', { name: 'Hot, then pull' });
    expect(within(pull).getByText('19 min').parentElement.textContent).toBe('19 min in the bath');
    expect(within(pull).getByText('38 min')).toBeTruthy(); // saved
    const drop = screen.getByRole('article', { name: 'Hot, then drop' });
    expect(within(drop).getByText('136°F, 130°F after 38 min')).toBeTruthy();
    expect(fetch.mock.calls[0][0]).toBe(
      'https://api.test/sousvide/plan?thickness_mm=38&shape=slab&start_c=5&target_c=54.5&boost_c=3&sear_s=45');

    await act(async () => { fireEvent.click(screen.getByRole('radio', { name: 'Tenderloin roast' })); });
    await vi.waitFor(() => expect(fetch.mock.calls.at(-1)[0]).toContain('thickness_mm=75&shape=cylinder'));
  });

  it('asks for a new plan only when a slider is let go', async () => {
    const fetch = vi.fn(async () => ({ ok: true, json: async () => PLAN }));
    vi.stubGlobal('fetch', fetch);
    await act(async () => { render(<SousVideApp />); });
    const slider = screen.getByRole('slider', { name: 'Hotter bath' });
    fireEvent.change(slider, { target: { value: '4' } });
    fireEvent.change(slider, { target: { value: '5' } });
    expect(screen.getByText('+9°F · 139°F')).toBeTruthy();
    expect(fetch).toHaveBeenCalledTimes(1);
    await act(async () => { fireEvent.pointerUp(slider); });
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[1][0]).toContain('boost_c=5');
  });

  it('shows the API error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({ detail: 'nope' }) })));
    await act(async () => { render(<SousVideApp />); });
    expect((await screen.findByRole('alert')).textContent).toBe('nope');
  });
});
