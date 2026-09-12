import { describe, expect, it } from 'vitest';
import { COMMONS_SCENE_CONTRACT, validateSceneSnapshot } from './contracts.js';

const base = {
  id: 'commons-home',
  layout_version: 7,
  version: 3,
  server_time_ms: 1800000000000,
  state: {
    schema_version: 2,
    objects: {},
    actors: { host: { id: 'host', asset: 'host', tile_x: 7, tile_y: 5 } },
  },
};

describe('Commons scene contract', () => {
  it('keeps legacy snapshots readable for the compatibility renderer', () => {
    expect(validateSceneSnapshot(base)).toEqual({ valid: true, legacy: true });
  });

  it('rejects unknown assets and out-of-bounds tile coordinates', () => {
    expect(validateSceneSnapshot({ ...base, state: { ...base.state, actors: { host: { asset: 'made-up', tile_x: 1, tile_y: 1 } } } }).valid).toBe(false);
    expect(validateSceneSnapshot({ ...base, state: { ...base.state, actors: { host: { asset: 'host', tile_x: 16, tile_y: 1 } } } }).valid).toBe(false);
  });

  it('accepts bounded legacy normalized coordinates', () => {
    expect(validateSceneSnapshot({
      ...base,
      state: {
        ...base.state,
        actors: { host: { asset: 'host', x: 0.285, y: 0.418 } },
      },
    })).toEqual({ valid: true, legacy: true });
  });

  it('rejects partial or malformed coordinate pairs instead of falling back', () => {
    const invalidActors = [
      { asset: 'host', tile_x: 7 },
      { asset: 'host', tile_x: '7', tile_y: 5 },
      { asset: 'host', tile_x: 7, tile_y: 5, x: -0.01, y: 0.5 },
      { asset: 'host', x: 0.5 },
      { asset: 'host', x: 1.01, y: 0.5 },
      { asset: 'host', x: 0.5, y: Infinity },
    ];

    invalidActors.forEach((actor) => {
      expect(validateSceneSnapshot({
        ...base,
        state: { ...base.state, actors: { host: actor } },
      }).valid).toBe(false);
    });
  });

  it('requires the new catalog and a valid ambient program for schema eight', () => {
    expect(validateSceneSnapshot({
      ...base,
      state: { ...base.state, schema_version: 8, catalog_version: 'old', ambient: { enabled: false, revision: 1, reason: 'legacy' } },
    }).valid).toBe(false);
  });

  it('describes a blocked room shell with a two-tile doorway', () => {
    expect(COMMONS_SCENE_CONTRACT.room_shell.blocked).toContainEqual([0, 0]);
    expect(COMMONS_SCENE_CONTRACT.room_shell.blocked).not.toContainEqual([7, 15]);
    expect(COMMONS_SCENE_CONTRACT.room_shell.doorway).toEqual([[7, 15], [8, 15]]);
  });

  it('does not treat a schema eight snapshot without a catalog as legacy', () => {
    expect(validateSceneSnapshot({
      ...base,
      state: { ...base.state, schema_version: 8, ambient: { enabled: false, revision: 1, reason: 'legacy' } },
    })).toEqual({ valid: false, error: 'scene catalog is unsupported' });
  });

  it('requires canonical tile anchors for schema eight entities', () => {
    expect(validateSceneSnapshot({
      ...base,
      state: {
        ...base.state,
        schema_version: 8,
        catalog_version: 'commons-room-v1',
        ambient: { enabled: false, revision: 1, reason: 'resting_only' },
        actors: { host: { asset: 'host', x: 0.5, y: 0.5 } },
      },
    })).toEqual({ valid: false, error: 'scene entity catalog or coordinates are invalid' });
  });

  it('rejects schema versions newer than the renderer understands', () => {
    expect(validateSceneSnapshot({
      ...base,
      state: { ...base.state, schema_version: 9, catalog_version: 'commons-room-v1' },
    })).toEqual({ valid: false, error: 'scene schema is unsupported' });
  });

  it('rejects non-integer schema versions', () => {
    expect(validateSceneSnapshot({
      ...base,
      state: { ...base.state, schema_version: 'seven' },
    })).toEqual({ valid: false, error: 'scene schema is invalid' });
  });
});
