import { describe, expect, it } from 'vitest';
import {
  COMMONS_GRID,
  findTilePath,
  isTileAvailable,
  normalizedToTile,
  tileDistance,
  pixelToTile,
  tileToNormalized,
  tileToPixel,
} from './commons-grid.js';

describe('Commons tile projection', () => {
  it('round-trips tile centers through the isometric projection', () => {
    const pixel = tileToPixel(7, 5);
    expect(pixelToTile(pixel.x, pixel.y)).toEqual({ tile_x: 7, tile_y: 5 });
  });

  it('round-trips normalized scene coordinates at a tile center', () => {
    const normalized = tileToNormalized(10, 4);
    expect(normalizedToTile(normalized.x, normalized.y)).toEqual({ tile_x: 10, tile_y: 4 });
  });

  it('measures movement in discrete Manhattan tile distance', () => {
    expect(tileDistance({ tile_x: 7, tile_y: 5 }, { tile_x: 10, tile_y: 3 })).toBe(5);
  });

  it('keeps movement inside the finite room grid', () => {
    expect(pixelToTile(-100, 300)).toEqual({
      tile_x: 0,
      tile_y: COMMONS_GRID.rows - 1,
    });
  });

  it('treats movable objects and actors as tile occupancy', () => {
    const state = {
      grid: { blocked: [[2, 2]] },
      objects: { chair: { id: 'chair', tile_x: 4, tile_y: 4 } },
      actors: { host: { id: 'host', tile_x: 6, tile_y: 6 } },
    };
    expect(isTileAvailable(state, { tile_x: 2, tile_y: 2 }, { entityType: 'actor', entityId: 'host' })).toBe(false);
    expect(isTileAvailable(state, { tile_x: 4, tile_y: 4 }, { entityType: 'actor', entityId: 'host' })).toBe(false);
    expect(isTileAvailable(state, { tile_x: 6, tile_y: 6 }, { entityType: 'actor', entityId: 'host' })).toBe(true);
  });

  it('reserves the full furniture footprint while moving a large prop', () => {
    const state = {
      objects: { 'record-console': { id: 'record-console', asset: 'record-console', tile_x: 2, tile_y: 5 } },
      actors: { host: { id: 'host', tile_x: 5, tile_y: 5 } },
    };
    expect(isTileAvailable(
      state,
      { tile_x: 4, tile_y: 5 },
      { entityType: 'object', entityId: 'record-console' },
    )).toBe(false);
  });

  it('finds a four-direction path around blocked tiles', () => {
    const state = {
      grid: { blocked: [[2, 2]] },
      objects: {},
      actors: { host: { id: 'host', tile_x: 1, tile_y: 2 } },
    };
    const path = findTilePath(
      state,
      { tile_x: 1, tile_y: 2 },
      { tile_x: 3, tile_y: 2 },
      { entityType: 'actor', entityId: 'host' },
    );

    expect(path.at(-1)).toEqual({ tile_x: 3, tile_y: 2 });
    expect(path).not.toContainEqual({ tile_x: 2, tile_y: 2 });
    expect(path.every((step, index) => {
      const prior = index === 0 ? { tile_x: 1, tile_y: 2 } : path[index - 1];
      return Math.abs(step.tile_x - prior.tile_x) + Math.abs(step.tile_y - prior.tile_y) === 1;
    })).toBe(true);
  });
});
