import { describe, expect, it } from 'vitest';
import { elementBounds, resizeRectFromCorner, snapElement } from './geometry';

describe('floor plan geometry', () => {
  it('keeps the opposite corner fixed when resizing a rotated item', () => {
    const start = { id: 'desk', type: 'furniture', x: 50, y: 50, width: 55, height: 55, rotation: 90 };
    const resized = resizeRectFromCorner(start, 'se', { x: 22.5, y: 77.5 }, { x: 12.5, y: 87.5 });
    expect(resized.width).toBe(65);
    expect(resized.height).toBe(65);
    expect(resized.x).toBeCloseTo(45);
    expect(resized.y).toBeCloseTo(55);
  });
  it('snaps using current resized bounds within two inches', () => {
    const wall = { id: 'wall', type: 'wall', x: 100, y: 0, length: 200, thickness: 4, rotation: 90 };
    const desk = { id: 'desk', type: 'furniture', x: 71, y: 0, width: 55, height: 55, rotation: 0 };
    const snapped = snapElement(desk, [wall, desk]);
    expect(elementBounds(snapped).right).toBe(elementBounds(wall).left);
  });
});
