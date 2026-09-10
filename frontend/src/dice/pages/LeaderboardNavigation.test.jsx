import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getEloLeaderboard: vi.fn(),
  getSinkLeaderboard: vi.fn(),
  getSelfSinkLeaderboard: vi.fn(),
}));

vi.mock('../api.js', () => ({ diceApi: mocks }));
vi.mock('../components/EloDistribution.jsx', () => ({
  default: () => null,
  summarizeRatings: () => ({ count: 0 }),
}));

import EloLeaderboard from './EloLeaderboard.jsx';
import SinkLeaderboard from './SinkLeaderboard.jsx';
import SelfSinkLeaderboard from './SelfSinkLeaderboard.jsx';

const auth = {};

describe('stats leaderboard navigation', () => {
  beforeEach(() => {
    mocks.getEloLeaderboard.mockResolvedValue([]);
    mocks.getSinkLeaderboard.mockResolvedValue([]);
    mocks.getSelfSinkLeaderboard.mockResolvedValue([]);
  });

  it.each([
    ['ELO', EloLeaderboard],
    ['sinks', SinkLeaderboard],
    ['self-sinks', SelfSinkLeaderboard],
  ])('returns from the %s leaderboard to player stats', async (_name, Page) => {
    render(<MemoryRouter><Page auth={auth} /></MemoryRouter>);

    expect(await screen.findByRole('link', { name: '← Player stats' })).toHaveAttribute('href', '/dice/stats');
  });

  it('filters the ELO leaderboard without changing its ranks', async () => {
    mocks.getEloLeaderboard.mockResolvedValue([
      { user_id: 'u1', display_name: 'Alice Adams', elo_rating: 1600, is_provisional: false },
      { user_id: 'u2', display_name: 'Bob Brown', elo_rating: 1500, is_provisional: false },
    ]);
    render(<MemoryRouter><EloLeaderboard auth={auth} /></MemoryRouter>);

    expect(await screen.findByText('Alice Adams')).toBeInTheDocument();
    fireEvent.change(screen.getByRole('textbox', { name: 'Search players' }), { target: { value: 'bob' } });

    expect(screen.queryByText('Alice Adams')).not.toBeInTheDocument();
    expect(screen.getByText('Bob Brown')).toBeInTheDocument();
    expect(screen.getByLabelText(/Rank 2, Bob Brown/)).toBeInTheDocument();
  });
});
