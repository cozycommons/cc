import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ getDuoDetail: vi.fn() }));
vi.mock('../api.js', () => ({ diceApi: mocks }));
vi.mock('../../analytics/usePageviewTracking', () => ({ usePageviewTracking: vi.fn() }));
vi.mock('../components/PlayerAvatar.jsx', () => ({ default: ({ profile }) => <span>{profile.display_name} avatar</span> }));

import DuoDetail from './DuoDetail.jsx';

describe('DuoDetail', () => {
  afterEach(() => vi.clearAllMocks());

  it('renders rating history, head-to-head records, and source game links', async () => {
    mocks.getDuoDetail.mockResolvedValue({
      summary: {
        duo_id: '3:u13:u2',
        members: [{ user_id: 'u1', display_name: 'Alpha' }, { user_id: 'u2', display_name: 'Bravo' }],
        elo: 1600,
        rating_deviation: 120,
        conservative_score: 1480,
        wins: 3,
        losses: 1,
        games: 4,
        win_rate: 0.75,
        rank: 1,
        current_streak: 2,
        best_streak: 3,
      },
      rating_history: [{ game_id: 'game-1', opponent_duo_id: 'other', before_elo: 1500, after_elo: 1525, delta: 25, result: 'win', score: [11, 8], played_at: '2026-01-01T00:00:00Z' }],
      games: [{ game_id: 'game-1', opponent_duo_id: 'other', before_elo: 1500, after_elo: 1525, delta: 25, result: 'win', score: [11, 8], played_at: '2026-01-01T00:00:00Z' }],
      head_to_head: [{ opponent_duo_id: 'other', wins: 1, losses: 0, games: 1, latest_meeting: '2026-01-01T00:00:00Z', game_ids: ['game-1'] }],
    });

    render(<MemoryRouter initialEntries={['/dice/stats/duos/3%3Au1%3Au2']}><Routes><Route path="/dice/stats/duos/:duoId" element={<DuoDetail auth={{ token: 'token' }} />} /></Routes></MemoryRouter>);

    expect(await screen.findByText('Alpha + Bravo')).toBeInTheDocument();
    expect(screen.getByText('Rank #1 · 4 games')).toBeInTheDocument();
    expect(screen.getByText('// RATING HISTORY')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /game-1/ })).toHaveAttribute('href', '/dice/game/game-1?duo=1');
    expect(screen.getByText('// HEAD TO HEAD')).toBeInTheDocument();
    expect(mocks.getDuoDetail).toHaveBeenCalledWith('token', '3:u1:u2');
  });
});
