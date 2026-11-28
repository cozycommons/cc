import React from 'react';
import { act, fireEvent, render, screen, within } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import SousVideApp, {
  CUTS, doneness, fmtClock, fmtCount, fmtDepth, fmtF, fmtInches, fmtMinutes, forgetPlans, readLog, recommended, screenFor, shade, sizedIn,
  sliceEarly, stepValue, summary,
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
const tap = (name) => act(async () => { fireEvent.click(screen.getByRole('button', { name })); });
const heading = () => screen.getByRole('heading', { level: 1 }).textContent;
// Steak, then cook, then the plan, the way a cook walks the flow.
async function toPlan() {
  await tap('Next');
  await tap('See the plan');
  return screen.findByRole('region', { name: 'What to do' });
}
// Sets a slider and lets go of it, which commits the value.
async function slide(name, value) {
  const slider = screen.getByRole('slider', { name });
  fireEvent.change(slider, { target: { value } });
  await act(async () => { fireEvent.pointerUp(slider); });
}
// The browser's own back button, which jsdom delivers as a later popstate.
const settle = () => new Promise((r) => { setTimeout(r, 30); });
const browserBack = () => act(async () => { window.history.back(); await settle(); });
// The page's Back walks history too, so it also lands a moment later.
const back = () => act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Back' })); await settle(); });

describe('Sous vide', () => {
  afterEach(() => {
    vi.unstubAllGlobals(); vi.useRealTimers(); forgetPlans(); localStorage.clear(); window.history.replaceState(null, '', '/');
  });

  it('formats temperatures, thickness and durations for a US kitchen', () => {
    expect([fmtF(54.5), fmtInches(38), fmtMinutes(18.8), fmtMinutes(152)]).toEqual(['130°F', '1.5″', '19 min', '2 h 32']);
    expect([0.4, 1.6, 9.5, 14.7, 30].map(fmtDepth)).toEqual(['none', '1/16″', '⅜″', '9/16″', '1 3/16″']);
  });

  it('shades meat from red to gray to crust as its peak temperature rises', () => {
    expect(shade(54)).not.toBe(shade(70));
    expect(shade(30)).toBe(shade(40));
    expect(shade(300)).toBe('rgb(84,52,34)');
  });

  it('names the doneness a target earns and reads an old text probe log in °F', () => {
    expect([52, 54.5, 60, 65].map(doneness)).toEqual(['rare', 'medium rare', 'medium', 'medium well']);
    expect(readLog('0, 41\n10 50\n\nnot a reading\n20;68')).toEqual([[0, 41], [10, 50], [20, 68]]);
  });

  it('steps on the fine grid inside its bounds, and sizes sides from the weight like the planner', () => {
    expect([stepValue(2.94, 0.05, { min: 0.15, max: 11, fine: 0.05 }), stepValue(0.2, -0.5, { min: 0.15, max: 11, fine: 0.05 }),
      stepValue(10.9, 0.5, { min: 0.15, max: 11, fine: 0.05 })]).toEqual([3, 0.15, 11]);
    // model.sized gives this steak 138 x 180 mm (PLAN.steak).
    const side = sizedIn({ cut: { shape: 'slab' }, mm: 51, lb: 2.94, widthIn: null, lengthIn: null });
    expect([Math.round(side.width * 25.4), Math.round(side.length * 25.4)]).toEqual([138, 180]);
    expect(Math.round(sizedIn({ cut: { shape: 'slab' }, mm: 51, lb: 2.94, widthIn: 5, lengthIn: null }).length * 25.4)).toBe(196);
  });

  it('leads with the recommended method as steps, and switches methods', async () => {
    const fetch = vi.fn(async () => ({ ok: true, json: async () => PLAN }));
    vi.stubGlobal('fetch', fetch);
    // The plan suspends; React 19 wants that render awaited inside act.
    await act(async () => { render(<SousVideApp />); });
    const answer = await toPlan();
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
    const answer = await toPlan();
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
    await tap('Next');
    await slide('Doneness', '52');
    await tap('See the plan');
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
    await tap('Next');
    await slide('Doneness', '52');
    await tap('See the plan');
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
    await toPlan();
    let when = screen.getByRole('region', { name: 'When' });
    expect(within(when).getAllByRole('listitem').map((li) => li.textContent))
      .toEqual(['NowInto the 136°F bath', '+19 minOut at 124°F, sear right away', '+25 minSear, rest, eat']);
    // The first tap starts from the earliest dinner, 6:30 PM on the quarter hour, and can't go before it.
    expect(within(when).getByRole('button', { name: 'Eat at −15' }).disabled).toBe(true);
    fireEvent.click(within(when).getByRole('button', { name: 'Eat at +1 h' }));
    expect(within(when).getByRole('group', { name: 'Eat at' }).querySelector('output').textContent).toBe('7:30 PM');
    expect(within(when).getAllByRole('listitem').map((li) => li.querySelector('time').textContent))
      .toEqual(['7:05 PM', '7:24 PM', '7:30 PM']);

    // Start cook sits in the sticky bar; starting swaps the plan screen for the cooking screen in place.
    expect(within(when).queryByRole('button', { name: 'Start cook' })).toBeNull();
    await tap('Start cook');
    expect([heading(), window.location.hash]).toEqual(['Cooking', '#cooking']);
    when = screen.getByRole('region', { name: 'When' }); // it moves above the steps, which fold away
    expect(screen.getByRole('region', { name: 'What to do' }).querySelector('.sv-when + .sv-recipe .sv-steps')).toBeTruthy();
    expect(within(when).getByText('Cooking since 6:00 PM')).toBeTruthy();
    expect(screen.queryByRole('radiogroup', { name: 'Method' })).toBeNull();
    // The calendar alarm rings 10 min before and at the pull, 18.8 min in.
    expect(within(when).getByRole('link', { name: 'Set alarms in my calendar' }).getAttribute('href'))
      .toBe(`https://api.test/sousvide/alarm.ics?start=${new Date(2026, 10, 27, 18, 0).getTime() / 1000}`
        + '&at=18.8&what=Out+at+124%C2%B0F%2C+sear+right+away');
    // The thermometer starts at what the model expects when the phone is picked up:
    // 41°F at the start, 101°F 12 min in.
    const reads = () => within(when).getByRole('group', { name: 'Thermometer reads, °F' }).querySelector('output').textContent;
    const wake = (minute) => act(() => {
      vi.setSystemTime(new Date(2026, 10, 27, 18, minute));
      document.dispatchEvent(new Event('visibilitychange'));
    });
    expect(reads()).toBe('41°F');
    wake(12);
    expect(reads()).toBe('101°F');
    fireEvent.click(within(when).getByRole('button', { name: 'Log' }));
    expect(within(when).getByText(/1 reading so far/)).toBeTruthy();
    // After a reading, the guess is that reading plus the model's rise since: 101 + 13.
    wake(19);
    expect(reads()).toBe('114°F');
    for (const step of ['+5', '+5']) fireEvent.click(within(when).getByRole('button', { name: `Thermometer reads, °F ${step}` }));
    expect(within(when).queryByText(/Out at 124°F/, { selector: '.sv-ready' })).toBeNull();
    fireEvent.click(within(when).getByRole('button', { name: 'Log' }));
    expect(within(when).getByText('Out at 124°F, sear right away', { selector: '.sv-ready' })).toBeTruthy();
    // The readings are kept in Learn, under Tune to your kitchen.
    await tap('Learn and tune');
    const readings = () => within(screen.getByRole('list', { name: 'Readings' })).getAllByRole('listitem').map((li) => li.textContent);
    expect(readings()).toEqual(['101°F at 12 min×', '124°F at 19 min×']);
    fireEvent.click(screen.getByRole('button', { name: 'Delete 101°F at 12 min' }));
    expect(readings()).toEqual(['124°F at 19 min×']);
    expect(JSON.parse(localStorage.getItem('sousvide.log'))).toEqual({ bathF: 135.5, readings: [[19, 124]] });
    expect(JSON.parse(localStorage.getItem('sousvide.cook'))).toMatchObject({ method: 'hot_and_pull', startMin: 1080 });

    await back();
    expect(heading()).toBe('Cooking');
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'End cook' })); });
    expect([heading(), window.location.hash]).toEqual(['The plan', '#plan']);
    expect(screen.getByRole('radiogroup', { name: 'Method' })).toBeTruthy();
    expect(localStorage.getItem('sousvide.cook')).toBeNull();
    expect(JSON.parse(localStorage.getItem('sousvide.log'))).toEqual({ bathF: 135.5, readings: [[19, 124]] });
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
    await toPlan();
    expect(planned(fetch)).toBe('https://api.test/sousvide/plan?thickness_mm=51&shape=slab&start_c=5&weight_g=1334'
      + '&bone=middle&target_c=54.5&boost_c=3&sear_s=45');
    await tap('Learn more: the chart, the cut and a replay');
    expect(screen.getByText(/Width and length from the weight: 5.43″ × 7.09″\. Thickness alone would say 1 h 13/).textContent)
      .toContain('next to the bone');

    // The chip goes back to the steak; width and length sit behind More.
    await tap('2″ bone-in ribeye, 2.94 lb · 130°F. Change the steak');
    expect(heading()).toBe('Your steak');
    fireEvent.click(screen.getByText('More: width and length'));
    // Width starts at the planner's 5.4″ from the weight; one fine step makes it 5.5″.
    expect(screen.getByRole('group', { name: 'Width, in' }).querySelector('output').textContent).toBe('≈5.4″from weight');
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Width, in +.1' })); });
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
    // An earlier version's text log, taken during a cook in a 135.5°F bath.
    localStorage.setItem('sousvide.log', JSON.stringify('0, 41\n20, 60\n40, 100\n60, 120'));
    localStorage.setItem('sousvide.cook', JSON.stringify({ method: 'classic', startedAt: 0, startMin: 0, bathF: '135.5' }));
    // A cook is running, so the page opens on it.
    await act(async () => { render(<SousVideApp />); });
    expect(heading()).toBe('Cooking');
    await tap('Learn and tune');
    expect(within(screen.getByRole('list', { name: 'Readings' })).getAllByRole('listitem')).toHaveLength(4);
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'Fit 4 readings' })); });
    expect((await screen.findByText(/Your steak heats 20% faster than the default/)).textContent)
      .toContain('Times now miss your readings by 0.5°F, against 6.7°F before. The log couldn’t tell');
    expect(screen.getByText('Diffusivity α 1.44 ×10⁻⁷ m²/s (default 1.2)')).toBeTruthy();
    const [, request] = fetch.mock.calls.find(([url]) => url.endsWith('/calibrate'));
    expect(JSON.parse(request.body)).toMatchObject({
      thickness_mm: 51, weight_g: 1334, bone: 'middle', start_c: 5, fit_h: true, readings: [[0, 5], [20, expect.closeTo(15.56, 2)],
        [40, expect.closeTo(37.78, 2)], [60, expect.closeTo(48.89, 2)]],
    });
    expect(JSON.parse(request.body).bath_c).toBeCloseTo(57.5, 2);
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
    await tap('Next');
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
    await tap('Next');
    await tap('See the plan');
    expect((await screen.findByRole('alert')).textContent).toBe('A measurement is out of range. Check the weight, width and length.');
  });

  it('shows the API error', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, json: async () => ({ detail: 'nope' }) })));
    await act(async () => { render(<SousVideApp />); });
    await tap('Next');
    await tap('See the plan');
    expect((await screen.findByRole('alert')).textContent).toBe('nope');
  });

  it('moves between screens in the URL hash, with Back and the browser back button', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => PLAN })));
    await act(async () => { render(<SousVideApp />); });
    const progress = () => screen.getByRole('progressbar', { name: 'Progress' }).getAttribute('aria-valuenow');
    expect([heading(), progress(), screen.queryByRole('button', { name: 'Back' })]).toEqual(['Your steak', '1', null]);
    await tap('Next');
    expect([heading(), window.location.hash, progress()]).toEqual(['Your cook', '#cook', '2']);
    expect(document.querySelector('.sv-screen').className).toContain('is-fwd');
    await tap('See the plan');
    expect([heading(), window.location.hash, progress()]).toEqual(['The plan', '#plan', '3']);
    // Back returns through history, so the phone's back button agrees with it.
    await back();
    expect([heading(), window.location.hash]).toEqual(['Your cook', '#cook']);
    expect(document.querySelector('.sv-screen').className).toContain('is-back');
    await browserBack();
    expect(heading()).toBe('Your steak');
  });

  it('goes back within the flow from a link straight to a later screen', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => PLAN })));
    window.history.replaceState(null, '', '/sousvide#plan');
    await act(async () => { render(<SousVideApp />); });
    expect(heading()).toBe('The plan');
    // Nothing in this flow came before, so Back replaces the entry instead of leaving the page.
    const entries = window.history.length;
    await back();
    expect([heading(), window.location.hash, window.history.length]).toEqual(['Your cook', '#cook', entries]);
    expect(screenFor('nonsense', false)).toBe('steak');
    expect(screenFor('cooking', false)).toBe('plan');
    expect([screenFor('', true), screenFor('plan', true), screenFor('steak', true), screenFor('learn', true)])
      .toEqual(['cooking', 'cooking', 'steak', 'learn']);
  });

  it('asks for the plan while the steak is set, so the plan screen shows at once', async () => {
    const fetch = vi.fn(async () => ({ ok: true, json: async () => PLAN }));
    vi.stubGlobal('fetch', fetch);
    await act(async () => { render(<SousVideApp />); });
    await tap('Next');
    await slide('Sear, each side', '60');
    expect(planned(fetch)).toContain('sear_s=60');
    const calls = fetch.mock.calls.length;
    await act(async () => { fireEvent.click(screen.getByRole('button', { name: 'See the plan' })); });
    // Already settled, so no loading message and no new request.
    expect(screen.getByRole('region', { name: 'What to do' })).toBeTruthy();
    expect(screen.queryByText('Working out the heat…')).toBeNull();
    expect(fetch.mock.calls.length).toBe(calls);
  });

  it('remembers the steak across a reload and names it on the summary chip', async () => {
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: true, json: async () => PLAN })));
    const { unmount } = await act(async () => render(<SousVideApp />));
    await act(async () => { fireEvent.click(screen.getByRole('radio', { name: 'Filet' })); });
    await tap('Next');
    await slide('Doneness', '57.5');
    unmount();
    await act(async () => { render(<SousVideApp />); });
    expect(heading()).toBe('Your cook');
    expect(screen.getByRole('button', { name: '1 15/16″ filet, 0.5 lb · 136°F. Change the steak' })).toBeTruthy();
    expect(summary({ cut: CUTS[4], mm: 76, lb: null, target: 54.5 })).toBe('3″ tenderloin roast · 130°F');
  });
});
