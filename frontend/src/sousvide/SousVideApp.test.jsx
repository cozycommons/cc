import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SousVideApp, {
  doneness, fmtDepth, fmtF, fmtInches, fmtMinutes, forgetPlans, parseLog, recommended, shade,
} from './SousVideApp.jsx';

vi.mock('../components/SiteHeader.jsx', () => ({ default: () => null }));
vi.mock('../api.js', () => ({ getUrl: () => 'https://api.test' }));

const row = (strategy, bath_c, minutes, extra = {}) => ({
  strategy, bath_c, minutes, switch_minutes: null, pull_core_c: 51, core_peak_c: 54, core_peak_range_c: [53.5, 54.4],
  bath_overcooked_mm: 0, overcooked_mm: 4.5,
  overcooked_pct: 45, gray_mm: 2.4, saved_minutes: 56.5 - minutes, extra_overcooked_mm: 0, ...extra,
});
// The bath, then a 45 s sear and a rest that peaks the center 6 min after the bath.
const trace = (end) => [
  ...[0, end / 2, end].map((min, i) => ({ min, phase: 'bath', core: [5, 40, 51][i], mid: 50, surface: 55 })),
  ...[[1, 52], [6, 54.2], [10, 54]].map(([after, core]) => ({ min: end + after, phase: 'finish', core, mid: 55, surface: 60 })),
];
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
    expect([0.4, 1.6, 9.5, 14.7, 30].map(fmtDepth)).toEqual(['none', '1/16″', '⅜″', '9/16″', '1 3/16″']);
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

  it('leads with the recommended method as steps, and switches methods', async () => {
    const fetch = vi.fn(async () => ({ ok: true, json: async () => PLAN }));
    vi.stubGlobal('fetch', fetch);
    // The plan suspends; React 19 wants that render awaited inside act.
    await act(async () => { render(<SousVideApp />); });
    const answer = await screen.findByRole('region', { name: 'What to do' });
    expect(within(answer).getByRole('radio', { name: 'Hot, then pull, 19 min' }).checked).toBe(true);
    expect(within(answer).getByText('Recommended')).toBeTruthy();
    const step = (key) => answer.querySelector(`[data-step="${key}"]`).textContent;
    expect(step('bath')).toBe('Set the bath to136°F');
    expect(step('probe')).toContain('¼ to ⅜″ from the bone');
    expect(step('out')).toBe('Take it out at124°Fon the thermometer, about 19 min in. Sear it right away.');
    // The pull aims within 1°F of the target, so its center reads as the target.
    expect(step('sear')).toBe('Sear45 s a sidethen rest 5 min. The center ends about 130°F, medium rare.'
      + 'Under the crust, 3/16″ a side cooks past medium rare. A longer sear browns more and cooks that layer deeper.');
    expect(within(answer).getByText(/^Fastest: 38 min faster than classic/)).toBeTruthy();
    expect(within(answer).getByText(/^Food safe at any length/)).toBeTruthy();
    expect(within(answer).getByText(/3\/16″ a side cooks past medium rare/)).toBeTruthy();

    // Cooling the bath before the steak is ready is its own step.
    fireEvent.click(within(answer).getByRole('radio', { name: 'Hot, then cool, 40 min' }));
    expect(step('cool')).toBe('Cool the bath to130°Fat 38 min. Ice works.');
    expect(step('out')).toContain('about 40 min in, or any time after.');
    expect(within(answer).queryByText('Recommended')).toBeNull();
    fireEvent.click(within(answer).getByRole('radio', { name: 'Classic, 57 min' }));
    expect(step('bath')).toBe('Set the bath to130°F');
  });

  it('cools the bath at the moment the steak is ready, not after it', async () => {
    const ready = { ...PLAN, hot_then_drop: row('hot_then_drop', 57.5, 40, { switch_minutes: 40 }) };
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => ready })));
    await act(async () => { render(<SousVideApp />); });
    const answer = await screen.findByRole('region', { name: 'What to do' });
    fireEvent.click(within(answer).getByRole('radio', { name: 'Hot, then cool, 40 min' }));
    expect(answer.querySelector('[data-step="cool"]').textContent)
      .toBe('Cool the bath to130°Fwhen it reads 124°F, about 40 min in. Ice works. It can then wait in the bath.');
    expect(answer.querySelector('[data-step="out"]')).toBeNull();
  });

  it('never says a steak below 130°F can wait, and flags a long cook there', async () => {
    const rare = {
      ...PLAN, classic: row('classic', 52, 300), hot_and_pull: row('hot_and_pull', 55, 200),
      hot_then_drop: row('hot_then_drop', 55, 250, { switch_minutes: 250 }),
    };
    vi.stubGlobal('fetch', vi.fn(async (url) => ({ ok: true, json: async () => (url.includes('target_c=52&') ? rare : PLAN) })));
    await act(async () => { render(<SousVideApp />); });
    const slider = screen.getByRole('slider', { name: 'Doneness' });
    fireEvent.change(slider, { target: { value: '52' } });
    await act(async () => { fireEvent.pointerUp(slider); });
    const answer = await screen.findByRole('region', { name: 'What to do' });
    await vi.waitFor(() => expect(within(answer).getByRole('radio', { name: 'Hot, then cool, 4 h 10' })).toBeTruthy());
    fireEvent.click(within(answer).getByRole('radio', { name: 'Hot, then cool, 4 h 10' }));
    expect(answer.textContent).not.toContain('wait');
    expect(answer.querySelector('[data-step="out"]').textContent).toContain('about 4 h 10 in.');
    expect(within(answer).getByRole('alert').textContent).toBe('Below 130°F, keep the whole cook under 4 h. This one takes 4 h 10.');
    fireEvent.click(within(answer).getByRole('radio', { name: 'Hot, then pull, 3 h 20' }));
    expect(within(answer).getByText(/^Food safe at any length/)).toBeTruthy();
  });

  it('recommends the classic cook when pulling early saves little or overcooks more', () => {
    expect(recommended(PLAN)).toBe('hot_and_pull');
    expect(recommended({ ...PLAN, hot_and_pull: { ...PLAN.hot_and_pull, saved_minutes: 5 } })).toBe('classic');
    expect(recommended({ ...PLAN, hot_and_pull: { ...PLAN.hot_and_pull, extra_overcooked_mm: 2 } })).toBe('classic');
  });

  it('plans the bone-in ribeye from its thickness and weight, then from what the cook measures', async () => {
    const fetch = vi.fn(async () => ({ ok: true, json: async () => PLAN }));
    vi.stubGlobal('fetch', fetch);
    await act(async () => { render(<SousVideApp />); });
    await screen.findByRole('region', { name: 'What to do' });
    expect(planned(fetch)).toBe('https://api.test/sousvide/plan?thickness_mm=51&shape=slab&start_c=5&weight_g=1334'
      + '&bone=middle&target_c=54.5&boost_c=3&sear_s=45');
    expect(screen.getByText(/Width and length from the weight: 5.43″ × 7.09″\. Thickness alone would say 1 h 13/).textContent)
      .toContain('next to the bone');

    fireEvent.change(screen.getByLabelText('Width, in'), { target: { value: '5.5' } });
    fireEvent.blur(screen.getByLabelText('Width, in'));
    await act(async () => { fireEvent.click(screen.getByRole('radio', { name: 'Along an edge' })); });
    await vi.waitFor(() => expect(planned(fetch)).toContain('weight_g=1334&width_mm=140&bone=edge'));

    await act(async () => { fireEvent.change(screen.getByLabelText('Cut'), { target: { value: 'roast' } }); });
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
    expect((await screen.findByText(/Your steak heats 20% faster than the default/)).textContent)
      .toContain('Times now miss your readings by 0.5°F, against 6.7°F before. The log couldn’t tell');
    expect(screen.getByText('Diffusivity α 1.44 ×10⁻⁷ m²/s (default 1.2)')).toBeTruthy();
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
    expect(screen.getByText('Tune to your kitchen').textContent).toBe('Tune to your kitchen');
    expect(localStorage.getItem('sousvide.calibration')).toBeNull();
  });

  it('asks for a new plan only when a slider is let go', async () => {
    const fetch = vi.fn(async () => ({ ok: true, json: async () => PLAN }));
    vi.stubGlobal('fetch', fetch);
    await act(async () => { render(<SousVideApp />); });
    const slider = screen.getByRole('slider', { name: 'Hot bath, for the faster methods' });
    fireEvent.change(slider, { target: { value: '4' } });
    fireEvent.change(slider, { target: { value: '5' } });
    expect(screen.getByText('139°F · +9°F')).toBeTruthy();
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
