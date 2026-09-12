import { describe, expect, it } from 'vitest';
import {
  COMMONS_FLOOR_BOUNDARY,
  assertValidTile,
  depthForGround,
  directionForDelta,
  getBackingStoreSize,
  groundToTile,
  nonNegativeModulo,
  projectGround,
  tileToGround,
  unprojectGround,
} from './geometry.js';

describe('Commons world geometry', () => {
  it('projects and unprojects fractional ground positions without rounding', () => {
    const point = projectGround(4.25, 8.75, 3);
    expect(unprojectGround(point.x, point.y, 3)).toEqual({ u: 4.25, v: 8.75 });
  });

  it('keeps floor perimeter on cell boundaries', () => {
    expect(COMMONS_FLOOR_BOUNDARY.map(({ u, v }) => projectGround(u, v))).toEqual([
      { x: 0, y: 0 },
      { x: 512, y: 0 },
      { x: 512, y: 512 },
      { x: 0, y: 512 },
    ]);
  });

  it('rejects invalid tiles instead of clamping them', () => {
    expect(() => assertValidTile(16, 5)).toThrow(/outside/);
    expect(groundToTile(-0.6, 5)).toBeNull();
    expect(tileToGround(3, 4)).toEqual({ u: 3, v: 4 });
  });

  it('maps cardinal movement to registered character views', () => {
    expect(directionForDelta(1, 0)).toBe('right');
    expect(directionForDelta(0, 1)).toBe('front');
    expect(directionForDelta(-1, 0)).toBe('left');
    expect(directionForDelta(0, -1)).toBe('back');
    expect(directionForDelta(1, 1)).toBeNull();
  });

  it('sorts equal ground positions by explicit depth offsets', () => {
    expect(depthForGround(2, 3)).toBe(96);
    expect(depthForGround(2, 3, -0.5)).toBe(95.5);
  });

  it('allocates the framebuffer from displayed size and capped DPR', () => {
    expect(getBackingStoreSize(850.4, 850.4, 3)).toEqual({
      width: 1701,
      height: 1701,
      dpr: 2,
    });
  });

  it('uses mathematical modulo for times before the epoch', () => {
    expect(nonNegativeModulo(-250, 180000)).toBe(179750);
  });
});
