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
  layout_version: 1,
  version: 7,
  updated_at: '2026-09-07T12:00:00Z',
  state: {
    schema_version: 1,
    objects: {
      'record-player': {
        id: 'record-player', kind: 'prop', x: 0.285, y: 0.418,
        movable: true, state: { playing: false },
      },
    },
    actors: {
      host: { id: 'host', kind: 'actor', x: 0.555, y: 0.595, facing: 'south' },
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
          'record-player': {
            ...scene.state.objects['record-player'],
            state: { playing: true },
          },
        },
      },
    });
  });

  afterEach(() => vi.clearAllMocks());

  it('renders the server scene and commits an object state change', async () => {
    render(<CommonsScene />);

    const recordPlayer = await screen.findByRole('button', { name: /record player/i });
    expect(screen.getByLabelText('Commons host')).toBeInTheDocument();

    fireEvent.click(recordPlayer);

    await waitFor(() => expect(mocks.sendSceneCommand).toHaveBeenCalledWith(
      expect.objectContaining({
        expected_version: 7,
        kind: 'set_object_state',
        payload: { object_id: 'record-player', state_key: 'playing', value: true },
      }),
      'browser-test',
    ));
  });
});
