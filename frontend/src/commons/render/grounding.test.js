import { describe, expect, it } from 'vitest';
import { getCommonsRenderMetadata } from '../commons-assets.js';
import { supportDepthOffset } from './grounding.js';

describe('legacy furniture support depth', () => {
  it('uses the visible support span rather than the nearest foot', () => {
    expect(supportDepthOffset(getCommonsRenderMetadata('dining-table'))).toBeCloseTo(-19.9941, 3);
    expect(supportDepthOffset(getCommonsRenderMetadata('orange-sofa'))).toBeCloseTo(-26.0417, 3);
    expect(supportDepthOffset(getCommonsRenderMetadata('host'))).toBe(0);
  });

  it('is independent of transparent padding and horizontal mirroring', () => {
    const original = {
      width: 100, sourceSizePx: [200, 200], anchor: [0.5, 0.9],
      supportPointsPx: [[20, 100], [160, 180]],
    };
    const padded = {
      width: 200, sourceSizePx: [400, 400], anchor: [0.5, 280 / 400],
      supportPointsPx: [[120, 200], [260, 280]],
    };
    const mirrored = { ...original, supportPointsPx: original.supportPointsPx.map(([x, y]) => [200 - x, y]) };
    expect(supportDepthOffset(original)).toBe(-20);
    expect(supportDepthOffset(padded)).toBe(supportDepthOffset(original));
    expect(supportDepthOffset(mirrored)).toBe(supportDepthOffset(original));
  });

  it('honors explicit displayed height for nonuniform source scaling', () => {
    expect(supportDepthOffset({
      width: 100, height: 200, sourceSizePx: [200, 200], anchor: [0.5, 0.9],
      supportPointsPx: [[20, 100], [160, 180]], depthOffset: 2,
    })).toBe(-38);
  });
});
