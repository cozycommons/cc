import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SousVideApp, { doneness, fmtF, fmtInches, fmtMinutes, forgetPlans, parseLog, shade } from './SousVideApp.jsx';

vi.mock('../components/SiteHeader.jsx', () => ({ default: () => null }));
vi.mock('../api.js', () => ({ getUrl: () => 'https://api.test' }));

const row = (strategy, bath_c, minutes, extra = {}) => ({
  strategy, bath_c, minutes, switch_minutes: null, pull_core_c: 51, core_peak_c: 54, core_peak_range_c: [53.5, 54.4],
  bath_overcooked_mm: 0, overcooked_mm: 4.5,
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
  thickness_only_minutes: 72.5,
  steak: { width_mm: 138, length_mm: 180, heated_width_mm: 96, bone: 'middle', sized_by: 'weight' },
};
const planned = (fetch) => fetch.mock.calls.filter(([url]) => url.includes('/plan?')).at(-1)[0];

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

  it('names the doneness a target earns and reads a probe log in °F', () => {
    expect([52, 54.5, 60, 65].map(doneness)).toEqual(['rare', 'medium rare', 'medium', 'medium well']);
    expect(parseLog('0, 41\n10 50\n\nnot a reading\n20;68')).toEqual([[0, 5], [10, 10], [20, 20]]);
  });

  it('plans the bone-in ribeye from its thickness and weight, then from what the cook measures', async () => {
    const fetch = vi.fn(async () => ({ ok: true, json: async () => PLAN }));
    vi.stubGlobal('fetch', fetch);
    // The plan suspends; React 19 wants that render awaited inside act.
    await act(async () => { render(<SousVideApp />); });
    const pull = await screen.findByRole('article', { name: 'Hot, then pull' });
    expect(within(pull).getByText('19 min').parentElement.textContent).toBe('19 min in the bath');
    expect(within(pull).getByText('38 min')).toBeTruthy(); // saved
    expect(within(pull).getByText('Pull when the core reads').nextSibling.textContent).toBe('124°F');
    expect(within(pull).getByText('Core peaks').nextSibling.textContent).toBe('129°F (128 to 130 by sear)');
    const drop = screen.getByRole('article', { name: 'Hot, then drop' });
    expect(within(drop).getByText('136°F, 130°F after 38 min')).toBeTruthy();
    expect(planned(fetch)).toBe('https://api.test/sousvide/plan?thickness_mm=51&shape=slab&start_c=5&weight_g=1334'
      + '&bone=middle&target_c=54.5&boost_c=3&sear_s=45');
    expect(screen.getByText(/Sized from the weight as 5.43″ × 7.09″\. Thickness alone would say 1 h 13/).textContent)
      .toContain('from the bone');

    fireEvent.change(screen.getByLabelText('Width, in'), { target: { value: '5.5' } });
    fireEvent.blur(screen.getByLabelText('Width, in'));
    await act(async () => { fireEvent.click(screen.getByRole('radio', { name: 'Along an edge' })); });
    await vi.waitFor(() => expect(planned(fetch)).toContain('weight_g=1334&width_mm=140&bone=edge'));

    await act(async () => { fireEvent.click(screen.getByRole('radio', { name: 'Tenderloin roast' })); });
    await vi.waitFor(() => expect(planned(fetch)).toBe(
      'https://api.test/sousvide/plan?thickness_mm=75&shape=cylinder&start_c=5&weight_g=1134&target_c=54.5&boost_c=3&sear_s=45'));
    expect(screen.queryByRole('radiogroup', { name: 'Bone' })).toBeNull();
  });

  it('fits a probe log and plans with the fitted constants', async () => {
    const fit = { alpha: 1.44, h_bath: 95, h_fitted: false, h_identifiable: false, alpha_on_bound: false, rms_c: 0.3, default_rms_c: 3.7 };
    const fetch = vi.fn(async (url) => ({ ok: true, json: async () => (url.endsWith('/calibrate') ? fit : PLAN) }));
    vi.stubGlobal('fetch', fetch);
    localStorage.clear();
    await act(async () => { render(<SousVideApp />); });
    fireEvent.change(screen.getByLabelText('Readings'), { target: { value: '0, 41\n20, 60\n40, 100\n60, 120' } });
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Fit 4 readings' })); });
    expect((await screen.findByText(/Fitted α 1.44 \(default 1.2\)/)).textContent)
      .toContain('The model now misses your readings by 0.5°F, against 6.7°F before. The log could not pin');
    const [, request] = fetch.mock.calls.find(([url]) => url.endsWith('/calibrate'));
    expect(JSON.parse(request.body)).toMatchObject({
      thickness_mm: 51, weight_g: 1334, bone: 'middle', start_c: 5, fit_h: true, readings: [[0, 5], [20, expect.closeTo(15.56, 2)],
        [40, expect.closeTo(37.78, 2)], [60, expect.closeTo(48.89, 2)]],
    });
    expect(JSON.parse(request.body).bath_c).toBeCloseTo(57.22, 2);
    await vi.waitFor(() => expect(planned(fetch)).toContain('&alpha=1.44'));
    expect(planned(fetch)).not.toContain('h_bath');
    expect(JSON.parse(localStorage.getItem('sousvide.calibration'))).toEqual({ alpha: 1.44 });

    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Back to defaults' })); });
    // The default plan is already cached, so going back needs no request.
    expect(screen.getByText('Calibrate from a probe log').textContent).toBe('Calibrate from a probe log');
    expect(localStorage.getItem('sousvide.calibration')).toBeNull();
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
