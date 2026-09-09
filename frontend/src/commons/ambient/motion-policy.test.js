import { describe, expect, it } from 'vitest';
import { resolveMotionPolicy } from './motion-policy.js';

describe('Commons motion policy', () => {
  it('animates an active visible scene', () => {
    expect(resolveMotionPolicy()).toMatchObject({ animate: true, paused: false, hidden: false });
  });

  it('freezes the complete displayed snapshot for pause, reduced motion, hidden tabs, or stale state', () => {
    expect(resolveMotionPolicy({ paused: true }).animate).toBe(false);
    expect(resolveMotionPolicy({ reducedMotion: true }).animate).toBe(false);
    expect(resolveMotionPolicy({ hidden: true }).animate).toBe(false);
    expect(resolveMotionPolicy({ stale: true })).toMatchObject({ stale: true, animate: false });
  });
});
