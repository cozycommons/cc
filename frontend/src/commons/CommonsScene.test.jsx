import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getScene: vi.fn(),
  getSceneClientId: vi.fn(() => 'browser-test'),
  sendSceneCommand: vi.fn(),
  clearPendingSceneCommand: vi.fn(),
  getPendingSceneCommand: vi.fn(() => null),
  savePendingSceneCommand: vi.fn(),
}));

vi.mock('./sceneApi.js', () => mocks);

import CommonsScene from './CommonsScene.jsx';

const scene = {
  id: 'commons-home',
  layout_version: 3,
  version: 7,
  updated_at: '2026-09-07T12:00:00Z',
  state: {
    schema_version: 2,
    objects: {
      'record-console': {
        id: 'record-console', kind: 'furniture', asset: 'record-console', tile_x: 0, tile_y: 5,
        movable: true, state: { playing: false },
      },
    },
    actors: {
      host: { id: 'host', kind: 'actor', asset: 'host', tile_x: 7, tile_y: 5, facing: 'south' },
    },
  },
};

describe('CommonsScene', () => {
  beforeEach(() => {
    mocks.getScene.mockResolvedValue(scene);
    mocks.sendSceneCommand.mockResolvedValue({
      accepted_version: 8,
      version: 8,
      replayed: false,
      state: {
        ...scene.state,
        objects: {
          ...scene.state.objects,
          'record-console': {
            ...scene.state.objects['record-console'],
            state: { playing: true },
          },
        },
      },
    });
  });

  afterEach(() => vi.clearAllMocks());

  it('renders the server scene and commits an object state change', async () => {
    render(<CommonsScene />);

    const recordPlayer = await screen.findByRole('button', { name: /^record console\./i });
    expect(screen.getByLabelText('Commons host')).toBeInTheDocument();

    fireEvent.click(recordPlayer);

    await waitFor(() => expect(mocks.sendSceneCommand).toHaveBeenCalledWith(
      expect.objectContaining({
        expected_version: 7,
        kind: 'set_object_state',
        payload: { object_id: 'record-console', state_key: 'playing', value: true },
      }),
      'browser-test',
    ));
  });

  it('persists a furniture orientation change', async () => {
    render(<CommonsScene />);

    const rotateRecordPlayer = await screen.findByRole('button', { name: /rotate record console/i });
    fireEvent.click(rotateRecordPlayer);

    await waitFor(() => expect(mocks.sendSceneCommand).toHaveBeenCalledWith(
      expect.objectContaining({
        expected_version: 7,
        kind: 'rotate_object',
        payload: { object_id: 'record-console', orientation: 'north' },
      }),
      'browser-test',
    ));
  });

  it('persists keyboard movement for the host one tile at a time', async () => {
    mocks.getScene.mockResolvedValue({
      ...scene,
      state: {
        ...scene.state,
        actors: { host: { ...scene.state.actors.host, facing: 'west' } },
      },
    });
    render(<CommonsScene />);

    const host = await screen.findByLabelText('Commons host');
    expect(host).toBeInTheDocument();

    fireEvent.keyDown(window, { key: 'ArrowLeft' });
    await waitFor(() => expect(mocks.sendSceneCommand).toHaveBeenCalledWith(
      expect.objectContaining({
        kind: 'walk_actor',
        payload: { actor_id: 'host', tile_x: 6, tile_y: 5 },
      }),
      'browser-test',
    ));
  });
});
