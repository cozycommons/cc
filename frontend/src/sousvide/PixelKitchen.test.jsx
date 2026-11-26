import { describe, expect, it } from 'vitest';
import { peaksAt, pointAt, sceneAt, tempAt } from './PixelKitchen.jsx';

const trace = [
  { min: 0, phase: 'bath', core: 5, mid: 5, surface: 5 },
  { min: 60, phase: 'bath', core: 50, mid: 55, surface: 57 },
  { min: 61, phase: 'finish', core: 51, mid: 56, surface: 95 },
  { min: 70, phase: 'finish', core: 54, mid: 55, surface: 40 },
];

describe('PixelKitchen', () => {
  it('reads temperature from the centre out through the middle to the surface', () => {
    expect([tempAt(trace[1], 0), tempAt(trace[1], 0.25), tempAt(trace[1], 0.5), tempAt(trace[1], 1)])
      .toEqual([50, 52.5, 55, 57]);
  });

  it('interpolates between trace readings', () => {
    expect(pointAt(trace, 30)).toMatchObject({ core: 27.5, surface: 31 });
    expect(pointAt(trace, 99)).toBe(trace.at(-1));
  });

  it('keeps each layer at its hottest, so the sear stays in the surface after it cools', () => {
    const peaks = peaksAt(trace, 70, 3);
    expect(peaks[2]).toBe(95);
    expect(peaks[0]).toBe(54);
  });

  it('knows when the steak is in the bath, the pan or resting', () => {
    expect([sceneAt(trace, 59, 45), sceneAt(trace, 60.5, 45), sceneAt(trace, 65, 45)]).toEqual(['bath', 'sear', 'rest']);
  });
});
