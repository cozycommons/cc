import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SousVideApp, {
  doneness, fmtClock, fmtCount, fmtDepth, fmtF, fmtInches, fmtMinutes, forgetPlans, parseLog, recommended, shade, sliceEarly,
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
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); forgetPlans(); localStorage.clear(); });

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
    // The same range as the cut-open view, unnamed since it spans rare and medium rare.
    expect(step('sear')).toBe('Sear45 s a sidethen rest 5 min. The center ends about 128 to 130°F.'
      + 'Under the crust, 3/16″ a side cooks past medium rare. A longer sear browns more and cooks that layer deeper.');
    expect(within(answer).getByText(/^Fastest of the three: 38 min faster than classic/)).toBeTruthy();
    expect(answer.textContent).not.toContain('safe');
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
    expect(answer.textContent).not.toContain('can then wait');
    expect(answer.querySelector('[data-step="out"]').textContent).toContain('about 4 h 10 in. Below 130°F it can’t wait, so skip cooling');
    expect(within(answer).getByRole('alert').textContent).toBe('Below 130°F, keep the whole cook under 4 h. This one takes 4 h 10.');
    fireEvent.click(within(answer).getByRole('radio', { name: 'Hot, then pull, 3 h 20' }));
    expect(within(answer).queryByRole('alert')).toBeNull();
  });

  it('keeps an early cool-down below 130°F and says to sear right away', async () => {
    const rare = { ...PLAN, hot_then_drop: row('hot_then_drop', 60, 87, { switch_minutes: 73 }) };
    vi.stubGlobal('fetch', vi.fn(async (url) => ({ ok: true, json: async () => (url.includes('target_c=52&') ? rare : PLAN) })));
    await act(async () => { render(<SousVideApp />); });
    const slider = screen.getByRole('slider', { name: 'Doneness' });
    fireEvent.change(slider, { target: { value: '52' } });
    await act(async () => { fireEvent.pointerUp(slider); });
    const answer = await screen.findByRole('region', { name: 'What to do' });
    await vi.waitFor(() => expect(within(answer).getByRole('radio', { name: 'Hot, then cool, 1 h 27' })).toBeTruthy());
    fireEvent.click(within(answer).getByRole('radio', { name: 'Hot, then cool, 1 h 27' }));
    expect(answer.querySelector('[data-step="cool"]').textContent).toBe('Cool the bath to126°Fat 1 h 13. Ice works.');
    expect(answer.querySelector('[data-step="out"]').textContent)
      .toBe('Take it out at124°Fon the thermometer, about 1 h 27 in. Below 130°F it can’t wait: sear right away.');
    expect(answer.textContent).not.toContain('skip cooling');
  });

  it('recommends the classic cook when pulling early saves little or overcooks more', () => {
    expect(recommended(PLAN)).toBe('hot_and_pull');
    expect(recommended({ ...PLAN, hot_and_pull: { ...PLAN.hot_and_pull, saved_minutes: 5 } })).toBe('classic');
    expect(recommended({ ...PLAN, hot_and_pull: { ...PLAN.hot_and_pull, extra_overcooked_mm: 2 } })).toBe('classic');
    // Never the one that breaks the 4 h rule below 130°F when the other does not.
    const long = { ...PLAN, hot_and_pull: { ...PLAN.hot_and_pull, bath_c: 53, minutes: 250, saved_minutes: 30 }, classic: row('classic', 53, 280) };
    expect(recommended({ ...long, classic: row('classic', 55, 200) })).toBe('classic');
    expect(recommended({ ...PLAN, hot_and_pull: { ...PLAN.hot_and_pull, saved_minutes: 5 }, classic: row('classic', 53, 300) })).toBe('hot_and_pull');
  });

  it('reads a schedule off the clock and says what cutting early gives up', () => {
    expect([0, 1145, -30, 720].map(fmtClock)).toEqual(['12:00 AM', '7:05 PM', '11:30 PM', '12:00 PM']);
    // A long rest: the center climbs from 51 to 54 over 15 min while the crust cools.
    const long = [{ min: 0, phase: 'bath', core: 5, surface: 55 }, { min: 60, phase: 'bath', core: 51, surface: 57 },
      ...Array.from({ length: 17 }, (_, i) => ({ min: 61 + i, phase: 'finish', core: Math.min(54, 51 + i * 0.2), surface: 80 - i * 2 }))];
    expect(sliceEarly(long, 60)).toEqual({ min: 5, core: 52, crust: 50 });
    expect(sliceEarly(trace(25), 45)).toBeNull(); // a 5 min rest leaves nothing to cut early
  });

  it('works back from dinner time, then runs the cook and logs the thermometer', async () => {
    const fetch = vi.fn(async () => ({ ok: true, json: async () => PLAN }));
    vi.stubGlobal('fetch', fetch);
    vi.useFakeTimers({ toFake: ['Date'] });
    vi.setSystemTime(new Date(2026, 10, 27, 18, 0));
    await act(async () => { render(<SousVideApp />); });
    let when = await screen.findByRole('region', { name: 'When' });
    expect(within(when).getAllByRole('listitem').map((li) => li.textContent))
      .toEqual(['NowInto the 136°F bath', '+19 minOut at 124°F, sear right away', '+25 minSear, rest, eat']);
    fireEvent.change(within(when).getByLabelText('Eat at'), { target: { value: '19:30' } });
    expect(within(when).getAllByRole('listitem').map((li) => li.querySelector('time').textContent))
      .toEqual(['7:05 PM', '7:24 PM', '7:30 PM']);

    fireEvent.click(within(when).getByRole('button', { name: 'Start cook' }));
    when = screen.getByRole('region', { name: 'When' }); // it moves above the steps while cooking
    expect(screen.getByRole('region', { name: 'What to do' }).querySelector('.sv-when + .sv-steps')).toBeTruthy();
    expect(within(when).getByText('Cooking since 6:00 PM')).toBeTruthy();
    expect(screen.queryByRole('radiogroup', { name: 'Method' })).toBeNull();
    expect(screen.getByLabelText('Bath °F').value).toBe('135.5');
    vi.setSystemTime(new Date(2026, 10, 27, 18, 12));
    fireEvent.change(within(when).getByLabelText('Thermometer reads, °F'), { target: { value: '41' } });
    fireEvent.click(within(when).getByRole('button', { name: 'Log' }));
    expect(screen.getByLabelText('Readings').value).toBe('12, 41');
    expect(within(when).getByText(/1 reading so far/)).toBeTruthy();
    expect(JSON.parse(localStorage.getItem('sousvide.cook'))).toMatchObject({ method: 'hot_and_pull', startMin: 1080 });

    fireEvent.click(within(when).getByRole('button', { name: 'End cook' }));
    expect(screen.getByRole('radiogroup', { name: 'Method' })).toBeTruthy();
    expect(localStorage.getItem('sousvide.cook')).toBeNull();
    expect(JSON.parse(localStorage.getItem('sousvide.log'))).toBe('12, 41');
  });

  it('measures thickness with a finger: its creases or fingers stacked', async () => {
    expect([1, 1.5, 0.75, 2.5].map(fmtCount)).toEqual(['1', '1½', '¾', '2½']);
    const fetch = vi.fn(async () => ({ ok: true, json: async () => PLAN }));
    vi.stubGlobal('fetch', fetch);
    await act(async () => { render(<SousVideApp />); });
    expect(screen.getByText('No ruler? Measure with your finger')).toBeTruthy();
    expect(screen.getByText('Stand your index finger up beside it, fingertip on the board.')).toBeTruthy();
    await act(async () => { fireEvent.click(screen.getByRole('radio', { name: 'the second crease' })); });
    await vi.waitFor(() => expect(planned(fetch)).toContain('thickness_mm=46&'));
    expect(screen.getByText(/Up to the second crease: about 1.81″\. Fingers differ by about 15%, about 30% on/)).toBeTruthy();
    fireEvent.click(screen.getByRole('radio', { name: 'Stacked' }));
    expect(screen.getByText(/^Tap where it reaches/)).toBeTruthy(); // 46 mm is no whole count of fingers
    await act(async () => { fireEvent.click(screen.getByRole('radio', { name: '3 fingers tall' })); });
    await vi.waitFor(() => expect(planned(fetch)).toContain('thickness_mm=57&'));
    expect(screen.getByText(/Up to 3 fingers: about 2.24″/)).toBeTruthy();
    expect(screen.queryByRole('radio', { name: 'Quarters' })).toBeNull();
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

  it('names an out-of-range measurement instead of printing the field errors', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 422, json: async () => ({ detail: [{ loc: ['query', 'weight_g'] }] }) })));
    await act(async () => { render(<SousVideApp />); });
    expect((await screen.findByRole('alert')).textContent).toBe('A measurement is out of range. Check the weight, width and length.');
  });

  it('shows the API error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({ detail: 'nope' }) })));
    await act(async () => { render(<SousVideApp />); });
    expect((await screen.findByRole('alert')).textContent).toBe('nope');
  });
});
