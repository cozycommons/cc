import { describe, expect, it } from 'vitest';
import { createPresentationClock } from './clock.js';

function harness() {
  let wall = 10_000;
  let mono = 100;
  const clock = createPresentationClock({ nowWall: () => wall, nowMono: () => mono });
  return {
    clock,
    advance(milliseconds) {
      wall += milliseconds;
      mono += milliseconds;
    },
    setWall(value) {
      wall = value;
    },
  };
}

describe('Commons presentation clock', () => {
  it('anchors server time at the request midpoint and advances monotonically', () => {
    const test = harness();
    test.clock.observe({ serverTimeMs: 20_000, midpointMs: 10_000, uncertaintyMs: 20 });
    test.advance(500);
    expect(test.clock.now()).toBe(20_500);
  });

  it('slews a small correction over two seconds without restarting phase', () => {
    const test = harness();
    test.clock.observe({ serverTimeMs: 20_000, midpointMs: 10_000, uncertaintyMs: 20 });
    test.advance(500);
    test.clock.observe({ serverTimeMs: 20_600, midpointMs: 10_500, uncertaintyMs: 20 });
    expect(test.clock.now()).toBeCloseTo(20_500);
    test.advance(1_000);
    expect(test.clock.now()).toBeCloseTo(21_550, 0);
    test.advance(1_000);
    expect(test.clock.now()).toBe(22_600);
  });

  it('slews a small negative correction without moving backwards', () => {
    const test = harness();
    test.clock.observe({ serverTimeMs: 20_000, midpointMs: 10_000, uncertaintyMs: 20 });
    test.advance(500);
    test.clock.observe({ serverTimeMs: 20_400, midpointMs: 10_500, uncertaintyMs: 20 });
    expect(test.clock.now()).toBe(20_500);
    test.advance(1_000);
    expect(test.clock.now()).toBeCloseTo(21_450, 0);
    test.advance(1_000);
    expect(test.clock.now()).toBe(22_400);
  });

  it('rebases repeated mid-slew polls without a discontinuity', () => {
    const test = harness();
    test.clock.observe({ serverTimeMs: 20_000, midpointMs: 10_000, uncertaintyMs: 20 });
    test.advance(500);
    test.clock.observe({ serverTimeMs: 20_600, midpointMs: 10_500, uncertaintyMs: 20 });
    test.advance(400);
    const beforeSecondPoll = test.clock.now();
    test.clock.observe({ serverTimeMs: 20_990, midpointMs: 10_900, uncertaintyMs: 20 });
    expect(test.clock.now()).toBeCloseTo(beforeSecondPoll);
    test.advance(400);
    const beforeThirdPoll = test.clock.now();
    test.clock.observe({ serverTimeMs: 21_390, midpointMs: 11_300, uncertaintyMs: 20 });
    expect(test.clock.now()).toBeCloseTo(beforeThirdPoll);
    test.advance(1_000);
    const afterPolls = test.clock.now();
    expect(afterPolls).toBeGreaterThan(beforeThirdPoll);
    test.advance(1_000);
    expect(test.clock.now()).toBeGreaterThan(afterPolls);
  });

  it('uses a monotonic anchor when the wall clock changes', () => {
    const test = harness();
    test.clock.observe({ serverTimeMs: 20_000, midpointMs: 10_000, uncertaintyMs: 20 });
    test.setWall(50_000);
    test.advance(250);
    expect(test.clock.now()).toBe(20_250);
  });

  it('rejects unreliable samples without changing the current clock', () => {
    const test = harness();
    expect(test.clock.observe({ serverTimeMs: 'later' })).toBe(false);
    expect(test.clock.now()).toBe(10_000);
    expect(test.clock.observe({
      serverTimeMs: 20_000,
      midpointMs: 10_000,
      uncertaintyMs: 501,
    })).toBe(false);
    expect(test.clock.now()).toBe(10_000);
    expect(test.clock.getPendingCorrection()).toBeNull();
  });

  it('keeps large positive corrections pending until an explicit reanchor', () => {
    const test = harness();
    test.clock.observe({ serverTimeMs: 20_000, midpointMs: 10_000, uncertaintyMs: 20 });
    test.advance(500);
    expect(test.clock.observe({ serverTimeMs: 21_000, midpointMs: 10_500, uncertaintyMs: 20 })).toBe(true);
    expect(test.clock.now()).toBe(20_500);
    expect(test.clock.getPendingCorrection()).toMatchObject({
      amountMs: 500,
      targetServerMs: 21_000,
      uncertaintyMs: 20,
    });
    test.advance(500);
    expect(test.clock.now()).toBe(21_000);
    expect(test.clock.reanchor()).toBe(true);
    expect(test.clock.getPendingCorrection()).toBeNull();
    expect(test.clock.now()).toBe(21_500);
  });

  it('keeps large negative corrections monotonic until an explicit reanchor', () => {
    const test = harness();
    test.clock.observe({ serverTimeMs: 20_000, midpointMs: 10_000, uncertaintyMs: 20 });
    test.advance(500);
    expect(test.clock.observe({ serverTimeMs: 19_500, midpointMs: 10_500, uncertaintyMs: 20 })).toBe(true);
    expect(test.clock.now()).toBe(20_500);
    expect(test.clock.getPendingCorrection()).toMatchObject({ amountMs: -1_000 });
    test.advance(500);
    expect(test.clock.now()).toBe(21_000);
    expect(test.clock.reanchor()).toBe(true);
    expect(test.clock.now()).toBe(20_000);
  });

  it('can be reset after an anchored sample', () => {
    const test = harness();
    test.clock.observe({ serverTimeMs: 20_000, midpointMs: 10_000, uncertaintyMs: 20 });
    test.clock.reset();
    expect(test.clock.now()).toBe(10_000);
    expect(test.clock.getPendingCorrection()).toBeNull();
    expect(test.clock.reanchor()).toBe(false);
  });
});
