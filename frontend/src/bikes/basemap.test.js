import { describe, expect, it } from 'vitest';
import { decode, tilesFor } from './basemap.js';

describe('basemap tiles', () => {
  it('decodes the delta-coded polylines bikes.basemap writes', () => {
    // backend/bikes/tests/test_basemap.py encodes this polyline.
    const points = decode([10, 20, 100, 0, 0, 500], -74.261, 40.47, 1e-5);
    const expected = [[-74.2609, 40.4702], [-74.2599, 40.4702], [-74.2599, 40.4752]];
    points.forEach(([lng, lat], i) => {
      expect(lng).toBeCloseTo(expected[i][0], 9);
      expect(lat).toBeCloseTo(expected[i][1], 9);
    });
  });

  it('asks only for tiles that exist around the view', () => {
    const index = { origin: [40.45, -74.3], tile: [0.01, 0.013], tiles: ['23_29', '24_29'] };
    expect(tilesFor(index, 40.742, -73.999, 40.757, -73.984)).toEqual([[23, 29], [24, 29]]);
  });
});
