import { describe, expect, it } from 'vitest';
import {
  barColor, drawKitchen, liveAt, minuteAt, painter, peaksAt, pointAt, sceneAt, storyAt, tempAt, timeline,
} from './PixelKitchen.jsx';

const trace = [
  { min: 0, phase: 'bath', core: 5, mid: 5, surface: 5 },
  { min: 60, phase: 'bath', core: 50, mid: 55, surface: 57 },
  { min: 61, phase: 'finish', core: 51, mid: 56, surface: 95 },
  { min: 70, phase: 'finish', core: 54, mid: 55, surface: 40 },
];

// The same shape with the solver's layers, as /sousvide/plan returns it: a 45 s
// sear after an hour's bath, then a long rest where the center climbs.
const rhos = [0, 0.5, 0.9, 1];
const at = (min, phase, layers) => ({ min, phase, core: layers[0], mid: layers[1], surface: layers.at(-1), layers });
const layered = [
  at(0, 'bath', [5, 5, 5, 5]),
  at(30, 'bath', [30, 40, 52, 56]),
  at(60, 'bath', [50, 54, 56, 57]),
  at(60.5, 'finish', [50, 54, 70, 120]),
  at(60.75, 'finish', [50, 54, 75, 130]),
  at(62, 'finish', [51, 55, 62, 60]),
  at(67, 'finish', [53, 55, 56, 52]),
  at(73, 'finish', [54.5, 55, 54, 49]),
  at(80, 'finish', [54, 54, 52, 47]),
];

describe('PixelKitchen', () => {
  it('reads temperature from the centre out through the middle to the surface', () => {
    expect([tempAt(trace[1], 0), tempAt(trace[1], 0.25), tempAt(trace[1], 0.5), tempAt(trace[1], 1)])
      .toEqual([50, 52.5, 55, 57]);
  });

  it('reads the solver layers when the plan has them, so the sear band stays thin', () => {
    const sear = layered[4];
    expect([tempAt(sear, 0, rhos), tempAt(sear, 0.7, rhos), tempAt(sear, 1, rhos)]).toEqual([50, 64.5, 130]);
    expect(tempAt(sear, 0.95, rhos)).toBeCloseTo(102.5);
    expect(liveAt(sear, 3, rhos)).toEqual([50, 54, 130]);
    expect(tempAt(sear, 0.7)).toBeCloseTo(84.4); // without rhos, the old three-point line
  });

  it('interpolates between trace readings, layers included', () => {
    expect(pointAt(trace, 30)).toMatchObject({ core: 27.5, surface: 31 });
    expect(pointAt(trace, 99)).toBe(trace.at(-1));
    expect(pointAt(layered, 45).layers).toEqual([40, 47, 54, 56.5]);
    expect(pointAt(trace, 30).layers).toBeUndefined();
  });

  it('keeps each layer at its hottest, so the sear stays in the surface after it cools', () => {
    const peaks = peaksAt(trace, 70, 3);
    expect(peaks[2]).toBe(95);
    expect(peaks[0]).toBe(54);
    expect(peaksAt(layered, 80, 3, rhos)).toEqual([54.5, 55, 130]);
  });

  it('knows when the steak is in the bath, the pan or resting', () => {
    expect([sceneAt(trace, 59, 45), sceneAt(trace, 60.5, 45), sceneAt(trace, 65, 45)]).toEqual(['bath', 'sear', 'rest']);
  });

  it('slows the replay down for the sear and the rest', () => {
    const knots = timeline(layered, 45);
    expect(knots.map(([f, t]) => [+f.toFixed(3), t])).toEqual([[0, 0], [0.55, 60], [0.7, 60.75], [1, 80]]);
    expect([minuteAt(knots, 0.275), minuteAt(knots, 0.625), minuteAt(knots, 1)]).toEqual([30, 60.375, 80]);
    expect(timeline(layered, 0)).toEqual([[0, 0], [0.55, 60], [0.55, 60], [1, 80]]); // no sear, no slow part
    expect(minuteAt(timeline(layered, 0), 0.55)).toBe(60);
  });

  it('tells the cook what is happening in plain words', () => {
    const row = { bath_c: 57.5, switch_minutes: null };
    const story = (t) => storyAt({ trace: layered, t, scene: sceneAt(layered, t, 45), row, target: 54.5, sear: 45, bathC: 57.5,
      point: pointAt(layered, t), next: pointAt(layered, Math.min(80, t + 0.5)) });
    expect(story(0)).toBe('Into the 136°F bath straight from the fridge, 41°F all the way through.');
    expect(story(30)).toBe('Heat creeps in from the outside. The edge is 133°F, the center 86°F.');
    expect(story(59)).toMatch(/^Nearly time to pull it/);
    expect(story(60.6)).toBe("Searing: the surface is 255°F, 266°F by the end of the sear, but only a thin layer gets that hot. The center, 122°F, hasn't felt it yet.");
    expect(story(62)).toMatch(/^Resting: .* still climbing \(124°F\) while the crust cools \(140°F\)/);
    expect(story(67)).toBe('Cut now and the center is 127°F. Wait and it reaches 130°F, but the crust cools to 120°F.');
    expect(story(80)).toBe('Rested: the center topped out at 130°F and the crust has cooled to 117°F. Slice it.');
    expect(storyAt({ trace: layered, t: 50, scene: 'bath', row: { bath_c: 60, switch_minutes: 40 }, target: 54.5, sear: 45, bathC: 54.5,
      point: pointAt(layered, 50), next: pointAt(layered, 50.5) })).toMatch(/^The bath is down to 130°F/);
  });

  it('colours a layer cool, at the target, past it, or searing', () => {
    expect([40, 54, 60, 80].map((c) => barColor(c, 54.5))).toEqual(['#8fb3b6', '#f0c477', '#b76845', '#8b3a2a']);
  });

  it('draws every scene inside the canvas', () => {
    const calls = [];
    const ctx = { fillRect: (x, y, w, h) => calls.push([x, y, w, h]) };
    for (const scene of ['bath', 'sear', 'rest']) {
      drawKitchen(painter(ctx), { scene, point: layered[4], peaks: liveAt(layered[4], 24, rhos), live: liveAt(layered[4], 24, rhos),
        bathF: 136, t: 61, tick: 500, marbling: [[3, 4]], fatCap: true, coreF: 122, crustF: 266, targetF: 130, targetC: 54.5,
        crust: 1, hot: true, done: scene === 'rest' });
    }
    expect(calls.every(([x, y, w, h]) => x >= 0 && y >= 0 && x + w <= 200 && y + h <= 112)).toBe(true);
  });
});
