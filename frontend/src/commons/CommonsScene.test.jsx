import React from 'react';
import { act, render, screen } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getScene: vi.fn(),
  sendSceneCommand: vi.fn(),
}));

vi.mock('./sceneApi.js', () => mocks);

import CommonsScene from './CommonsScene.jsx';

const scene = {
  id: 'commons-home',
  layout_version: 3,
  version: 7,
  server_time_ms: 1800000000000,
  updated_at: '2026-09-07T12:00:00Z',
  state: {
    schema_version: 2,
    ambient: { enabled: true, revision: 1, cycle_ms: 180000 },
    objects: {
      'record-console': {
        id: 'record-console', kind: 'furniture', asset: 'record-console', tile_x: 0, tile_y: 5,
        movable: true, state: { playing: false },
      },
    },
    actors: {
      host: { id: 'host', kind: 'actor', asset: 'host', tile_x: 7, tile_y: 5, facing: 'south' },
      maker: { id: 'maker', kind: 'actor', asset: 'maker', tile_x: 4, tile_y: 7, facing: 'south' },
    },
  },
};

describe('CommonsScene', () => {
  beforeEach(() => {
    mocks.getScene.mockResolvedValue(scene);
  });

  afterEach(() => vi.clearAllMocks());

  it('starts a fresh request after a StrictMode effect remount', async () => {
    let resolveAbandoned;
    mocks.getScene.mockImplementationOnce(() => new Promise((resolve) => { resolveAbandoned = resolve; }));
    render(<React.StrictMode><CommonsScene /></React.StrictMode>);
    expect(await screen.findByText(/2 residents and 1 placed object/)).toBeInTheDocument();
    expect(mocks.getScene).toHaveBeenCalledTimes(2);
    await act(async () => {
      resolveAbandoned({ ...scene, version: 8, state: { ...scene.state, actors: {} } });
    });
    expect(screen.getByText(/2 residents and 1 placed object/)).toBeInTheDocument();
  });

  it('renders the canonical room as an interactive top-down scene', async () => {
    render(<CommonsScene />);

    expect(await screen.findByRole('img', { name: 'Interactive top-down tile-based Cozy Commons room' })).toBeInTheDocument();
    expect(screen.getByText(/2 residents and 1 placed object/)).toBeInTheDocument();
    expect(screen.getByText(/WASD \/ arrows to walk/)).toBeInTheDocument();
    expect(mocks.sendSceneCommand).not.toHaveBeenCalled();
  });
});
