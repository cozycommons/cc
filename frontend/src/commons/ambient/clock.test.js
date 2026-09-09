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
    test.clock.observe({ serverTimeMs: 20_620, midpointMs: 10_500, uncertaintyMs: 20 });
    expect(test.clock.now()).toBeCloseTo(20_500);
    test.advance(1_000);
    expect(test.clock.now()).toBeCloseTo(21_560, 0);
    test.advance(1_000);
    expect(test.clock.now()).toBe(22_620);
  });

  it('uses a monotonic anchor when the wall clock changes', () => {
    const test = harness();
    test.clock.observe({ serverTimeMs: 20_000, midpointMs: 10_000, uncertaintyMs: 20 });
    test.setWall(50_000);
    test.advance(250);
    expect(test.clock.now()).toBe(20_250);
  });

  it('ignores malformed samples and can be reset', () => {
    const test = harness();
    expect(test.clock.observe({ serverTimeMs: 'later' })).toBe(false);
    expect(test.clock.now()).toBe(10_000);
    test.clock.observe({ serverTimeMs: 20_000, midpointMs: 10_000 });
    test.clock.reset();
    expect(test.clock.now()).toBe(10_000);
  });
});
