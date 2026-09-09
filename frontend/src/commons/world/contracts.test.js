import { describe, expect, it } from 'vitest';
import { validateSceneSnapshot } from './contracts.js';

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

  it('requires the new catalog and a valid ambient program for schema seven', () => {
    expect(validateSceneSnapshot({
      ...base,
      state: { ...base.state, schema_version: 7, catalog_version: 'old', ambient: { enabled: false, revision: 1, reason: 'legacy' } },
    }).valid).toBe(false);
  });

  it('rejects schema versions newer than the renderer understands', () => {
    expect(validateSceneSnapshot({
      ...base,
      state: { ...base.state, schema_version: 8, catalog_version: 'commons-v2' },
    })).toEqual({ valid: false, error: 'scene schema is unsupported' });
  });

  it('rejects non-integer schema versions', () => {
    expect(validateSceneSnapshot({
      ...base,
      state: { ...base.state, schema_version: 'seven' },
    })).toEqual({ valid: false, error: 'scene schema is invalid' });
  });
});
