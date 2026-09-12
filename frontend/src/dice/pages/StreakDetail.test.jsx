import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ getGames: vi.fn() }));
vi.mock('../api.js', () => ({ diceApi: mocks }));

import StreakDetail from './StreakDetail.jsx';

describe('StreakDetail', () => {
  afterEach(() => vi.clearAllMocks());

  it('shows exact ranked games with teammate, opponents, score, date, and links', async () => {
    mocks.getGames.mockResolvedValue([
      { id: 'g1', ranked: true, played_at: '2026-01-01T00:00:00Z', winner_team: 1, team1_score: 11, team2_score: 8, players: [
        { user_id: 'u1', display_name: 'Alpha', team: 1 }, { user_id: 'u2', display_name: 'Bravo', team: 1 }, { user_id: 'u3', display_name: 'Charlie', team: 2 },
      ] },
      { id: 'g2', ranked: true, played_at: '2026-01-02T00:00:00Z', winner_team: 1, team1_score: 11, team2_score: 9, players: [
        { user_id: 'u1', display_name: 'Alpha', team: 1 }, { user_id: 'u4', display_name: 'Delta', team: 1 }, { user_id: 'u3', display_name: 'Charlie', team: 2 },
      ] },
    ]);
    render(<MemoryRouter initialEntries={['/dice/stats/streaks/u1']}><Routes><Route path="/dice/stats/streaks/:userId" element={<StreakDetail />} /></Routes></MemoryRouter>);

    expect(await screen.findByText('Alpha')).toBeInTheDocument();
    expect(screen.getByText('WIN STREAK')).toBeInTheDocument();
    expect(screen.getByText('ACTIVE')).toBeInTheDocument();
    expect(screen.getByText('BEST')).toBeInTheDocument();
    expect(screen.getByText('ACTIVE').previousSibling).toHaveTextContent('2');
    expect(screen.getByText('BEST').previousSibling).toHaveTextContent('2');
    expect(screen.getAllByText('W')).toHaveLength(2);
    expect(screen.getByText('// CURRENT & BEST RUN')).toBeInTheDocument();
    expect(screen.queryByText('// ACTIVE STREAK')).not.toBeInTheDocument();
    expect(screen.queryByText('// BEST RUN')).not.toBeInTheDocument();
    expect(screen.getAllByText('with Bravo · vs Charlie')).toHaveLength(1);
    expect(screen.getAllByRole('link', { name: /11–8|11–9/ })).toHaveLength(2);
    expect(screen.getByRole('link', { name: /11–8/ })).toHaveAttribute('href', '/dice/game/g1');
  });
});
