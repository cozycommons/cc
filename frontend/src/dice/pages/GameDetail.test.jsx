import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ getGame: vi.fn(), deleteGame: vi.fn() }));
vi.mock('../api.js', () => ({ diceApi: mocks }));
vi.mock('../components/PlayerAvatar.jsx', () => ({ default: ({ profile }) => <span>{profile.display_name}</span> }));
vi.mock('../components/CommentsSection.jsx', () => ({ default: () => null }));
vi.mock('@/components/ui/button', () => ({ Button: ({ children, ...props }) => <button {...props}>{children}</button> }));

import GameDetail from './GameDetail.jsx';

describe('GameDetail', () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.restoreAllMocks();
    window.sessionStorage.clear();
  });

  it('passes duo evidence query and auth token through to the game API', async () => {
    mocks.getGame.mockResolvedValue({
      id: 'duo-game',
      created_by: 'u1',
      ranked: true,
      duo_only: true,
      team1_score: 11,
      team2_score: 8,
      winner_team: 1,
      played_at: '2026-01-01T00:00:00Z',
      created_at: '2026-01-01T00:00:00Z',
      players: [
        { user_id: 'u1', display_name: 'Alpha', team: 1, self_sinks: 0, sinks: 0 },
        { user_id: 'u2', display_name: 'Bravo', team: 1, self_sinks: 0, sinks: 0 },
        { user_id: 'u3', display_name: 'Charlie', team: 2, self_sinks: 0, sinks: 0 },
        { user_id: 'u4', display_name: 'Delta', team: 2, self_sinks: 0, sinks: 0 },
      ],
    });

    render(
      <MemoryRouter initialEntries={['/dice/game/duo-game?duo=1']}>
        <Routes><Route path="/dice/game/:gameId" element={<GameDetail auth={{ user: null, token: 'duo-token', isAdmin: false }} />} /></Routes>
      </MemoryRouter>,
    );

    await waitFor(() => expect(mocks.getGame).toHaveBeenCalledWith('duo-game', true, 'duo-token'));
    expect(await screen.findByText('11 – 8')).toBeInTheDocument();
  });

  it('reuses the deletion key when retrying after a lost response', async () => {
    vi.spyOn(window, 'confirm').mockReturnValue(true);
    const game = {
      id: 'game-1', created_by: 'u1', ranked: true, duo_only: false,
      team1_score: 5, team2_score: 1, winner_team: 1,
      played_at: '2026-01-01T00:00:00Z', created_at: '2026-01-01T00:00:00Z',
      players: [
        { user_id: 'u1', display_name: 'Alpha', team: 1, self_sinks: 0, sinks: 0 },
        { user_id: 'u2', display_name: 'Bravo', team: 1, self_sinks: 0, sinks: 0 },
        { user_id: 'u3', display_name: 'Charlie', team: 2, self_sinks: 0, sinks: 0 },
        { user_id: 'u4', display_name: 'Delta', team: 2, self_sinks: 0, sinks: 0 },
      ],
    };
    mocks.getGame.mockResolvedValueOnce(game).mockRejectedValueOnce(new Error('not found'));
    mocks.deleteGame.mockRejectedValueOnce(new Error('connection lost')).mockResolvedValueOnce({ deleted: true });
    const firstRender = render(
      <MemoryRouter initialEntries={['/dice/game/game-1']}>
        <Routes>
          <Route path="/dice/game/:gameId" element={<GameDetail auth={{ user: { id: 'u1' }, token: 'token', isAdmin: false }} />} />
          <Route path="/dice" element={<p>Dice home</p>} />
        </Routes>
      </MemoryRouter>,
    );

    fireEvent.click(await screen.findByRole('button', { name: 'Delete' }));
    expect(await screen.findByText('connection lost')).toBeInTheDocument();
    firstRender.unmount();
    render(
      <MemoryRouter initialEntries={['/dice/game/game-1']}>
        <Routes>
          <Route path="/dice/game/:gameId" element={<GameDetail auth={{ user: { id: 'u1' }, token: 'token', isAdmin: false }} />} />
          <Route path="/dice" element={<p>Dice home</p>} />
        </Routes>
      </MemoryRouter>,
    );
    await screen.findByText('Dice home');
    expect(mocks.deleteGame).toHaveBeenCalledTimes(2);
    expect(mocks.deleteGame.mock.calls[1][2]).toBe(mocks.deleteGame.mock.calls[0][2]);
  });

  it('shows canonical recorded player stats for a completed live game', async () => {
    mocks.getGame.mockResolvedValue({
      id: 'live-result', created_by: 'u1', ranked: true, duo_only: false,
      source_live_match_id: 'live-1', team1_score: 5, team2_score: 3, winner_team: 1,
      played_at: '2026-01-01T00:00:00Z', created_at: '2026-01-01T00:00:00Z',
      players: [
        { user_id: 'u1', display_name: 'Alpha', team: 1, self_sinks: 0, sinks: 0 },
        { user_id: 'u2', display_name: 'Bravo', team: 1, self_sinks: 0, sinks: 0 },
        { user_id: 'u3', display_name: 'Charlie', team: 2, self_sinks: 0, sinks: 0 },
        { user_id: 'u4', display_name: 'Delta', team: 2, self_sinks: 0, sinks: 0 },
      ],
      recorded_stats: {
        coverage: 'partial', observations: 3, outcomes: { point: 1, caught: 1, miss: 1 },
        players: {
          u1: { outcomes: { point: 1, caught: 1 }, table_catches: 0 },
          u2: { outcomes: {}, table_catches: 1 },
          u3: { outcomes: { miss: 1 } },
          u4: { outcomes: {} },
        },
      },
    });

    render(
      <MemoryRouter initialEntries={['/dice/game/live-result']}>
        <Routes><Route path="/dice/game/:gameId" element={<GameDetail auth={{ user: null, token: null, isAdmin: false }} />} /></Routes>
      </MemoryRouter>,
    );

    expect(await screen.findByRole('region', { name: 'Player game stats' })).toBeInTheDocument();
    expect(screen.getByText('3 recorded throws')).toBeInTheDocument();
    expect(screen.getByLabelText('1 catch')).toBeInTheDocument();
    expect(screen.getByText('Missing plays are excluded, not counted as misses.')).toBeInTheDocument();
  });
});
