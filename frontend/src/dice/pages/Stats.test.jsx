import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getAllGames: vi.fn(), getDuoLadder: vi.fn(), getEloLeaderboard: vi.fn(),
  getSinkLeaderboard: vi.fn(), getSelfSinkLeaderboard: vi.fn(), calculateStreaks: vi.fn(),
}));

vi.mock('../api.js', () => ({ diceApi: mocks }));
vi.mock('../../analytics/usePageviewTracking', () => ({ usePageviewTracking: vi.fn() }));
vi.mock('../components/PlayerAvatar.jsx', () => ({ default: ({ profile }) => <span>{profile.display_name} avatar</span> }));
vi.mock('../components/EloDistribution.jsx', () => ({ default: () => <div>Rating distribution chart</div> }));
vi.mock('../components/SinkLeadersChart.jsx', () => ({ default: () => <div>Scoring chart</div> }));
vi.mock('./Home.jsx', () => ({ calculateStreaks: mocks.calculateStreaks }));

import Stats from './Stats.jsx';

const profiles = [
  { user_id: 'u1', display_name: 'Alpha', avatar_url: null, team: 1 },
  { user_id: 'u2', display_name: 'Bravo', avatar_url: null, team: 2 },
];
const recordedGame = {
  id: 'g1', players: profiles,
  recorded_stats: {
    schema_version: 'dice-recorded-stats/v1', coverage: 'partial', observations: 12,
    players: {
      u1: { outcomes: { point: 2, caught: 2, miss: 1, fifa: 1 }, fifa_goals: 1, fifa_kicks: 1 },
      u2: { outcomes: { caught: 1, miss: 5 }, table_catches: 2 },
    },
  },
};

describe('Dice Stats', () => {
  beforeEach(() => {
    mocks.calculateStreaks.mockReturnValue([
      { user_id: 'u1', display_name: 'Alpha', avatar_url: null, current: 3, best: 4 },
      { user_id: 'u2', display_name: 'Bravo', avatar_url: null, current: 0, best: 6 },
    ]);
    mocks.getAllGames.mockResolvedValue([recordedGame]);
    mocks.getEloLeaderboard.mockResolvedValue([
      { user_id: 'u1', display_name: 'Alpha', elo_rating: 1612, is_provisional: false },
      { user_id: 'u2', display_name: 'Bravo', elo_rating: 1490, is_provisional: false },
    ]);
    mocks.getSinkLeaderboard.mockResolvedValue([]);
    mocks.getSelfSinkLeaderboard.mockResolvedValue([]);
    mocks.getDuoLadder.mockResolvedValue({ ranked: [], to_watch: [] });
  });
  afterEach(() => vi.clearAllMocks());

  it('shows rating, scoring, and recorded player attribution as one rich player view', async () => {
    render(<MemoryRouter><Stats auth={{ profile: { user_id: 'u1' } }} /></MemoryRouter>);

    expect(await screen.findByText('Rating distribution chart')).toBeInTheDocument();
    expect(await screen.findByLabelText('Recorded player attribution')).toBeInTheDocument();
    expect(screen.getByText('Scoring chart')).toBeInTheDocument();
    expect(screen.getByText('12')).toBeInTheDocument();
    expect(screen.getAllByText('67%')).toHaveLength(2);
    expect(screen.getByText('2 table · 0 FIFA')).toBeInTheDocument();
    expect(screen.getByText('Missing plays are excluded, not counted as misses.')).toBeInTheDocument();
  });

  it('uses a direct empty state when no live game has recorded stats', async () => {
    mocks.getAllGames.mockResolvedValue([]);
    render(<MemoryRouter><Stats auth={{}} /></MemoryRouter>);

    expect(await screen.findByText('No stats yet! Play a game using the Live Game Feature.')).toBeInTheDocument();
  });

  it.each([2, 4])('shows every player in a %s-way tie for first', async (tieSize) => {
    mocks.getEloLeaderboard.mockResolvedValue(Array.from({ length: tieSize }, (_, index) => ({
      user_id: `t${index}`,
      display_name: `Leader ${index + 1}`,
      elo_rating: 1600,
      is_provisional: false,
    })));

    render(<MemoryRouter><Stats auth={{}} /></MemoryRouter>);

    expect(await screen.findByLabelText(`${tieSize} players tied for first`)).toBeInTheDocument();
    for (let index = 0; index < tieSize; index += 1) {
      expect(screen.getByText(`Leader ${index + 1}`)).toBeInTheDocument();
    }
    expect(screen.queryByText('#1 PLAYER')).not.toBeInTheDocument();
  });

  it('shows every recorded-play metric leader when the top value is tied', async () => {
    mocks.getAllGames.mockResolvedValue([{
      id: 'tie-game',
      players: profiles,
      recorded_stats: {
        observations: 4,
        coverage: 'complete',
        players: {
          u1: { outcomes: { point: 2 } },
          u2: { outcomes: { point: 2 } },
        },
      },
    }]);

    render(<MemoryRouter><Stats auth={{}} /></MemoryRouter>);

    expect(await screen.findByLabelText('2 players tied for scores')).toBeInTheDocument();
  });

  it('uses a distinct streak view with an active run and historical bars', async () => {
    render(<MemoryRouter><Stats auth={{}} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('tab', { name: 'streaks' }));

    expect(await screen.findByRole('region', { name: 'Win streaks' })).toBeInTheDocument();
    expect(screen.getByText('ACTIVE RUN')).toBeInTheDocument();
    expect(screen.getByLabelText('Longest win streaks')).toBeInTheDocument();
  });

  it('shows tied active streak leaders and uses competition ranks for tied records', async () => {
    mocks.calculateStreaks.mockReturnValue([
      { user_id: 'u1', display_name: 'Alpha', avatar_url: null, current: 3, best: 5 },
      { user_id: 'u2', display_name: 'Bravo', avatar_url: null, current: 3, best: 5 },
      { user_id: 'u3', display_name: 'Charlie', avatar_url: null, current: 2, best: 4 },
    ]);
    render(<MemoryRouter><Stats auth={{}} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('tab', { name: 'streaks' }));

    expect(await screen.findByLabelText('2 players tied for the longest active streak')).toBeInTheDocument();
    expect(screen.getByLabelText('Alpha, 5 wins, rank 1')).toBeInTheDocument();
    expect(screen.getByLabelText('Bravo, 5 wins, rank 1')).toBeInTheDocument();
    expect(screen.getByLabelText('Charlie, 4 wins, rank 3')).toBeInTheDocument();
    expect(screen.getByText(/Also active/)).toBeInTheDocument();
  });

  it('keeps every streak tied at the fifth rank instead of truncating people', async () => {
    mocks.calculateStreaks.mockReturnValue([
      { user_id: 'u1', display_name: 'One', current: 0, best: 9 },
      { user_id: 'u2', display_name: 'Two', current: 0, best: 8 },
      { user_id: 'u3', display_name: 'Three', current: 0, best: 7 },
      { user_id: 'u4', display_name: 'Four', current: 0, best: 6 },
      { user_id: 'u5', display_name: 'Five A', current: 0, best: 5 },
      { user_id: 'u6', display_name: 'Five B', current: 0, best: 5 },
    ]);
    render(<MemoryRouter><Stats auth={{}} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('tab', { name: 'streaks' }));

    expect(await screen.findByLabelText('Five A, 5 wins, rank 5')).toBeInTheDocument();
    expect(screen.getByLabelText('Five B, 5 wins, rank 5')).toBeInTheDocument();
  });

  it('separates a ranked duo hero from provisional pairs', async () => {
    mocks.getDuoLadder.mockResolvedValue({
      ranked: [{ duo_id: '3:u13:u2', members: profiles, elo: 1612, wins: 4, losses: 1, games: 5, win_rate: 0.8, rank: 1 }],
      to_watch: [{
        duo_id: '3:u23:u3', members: [{ user_id: 'u2', display_name: 'Bravo' }, { user_id: 'u3', display_name: 'Charlie' }],
        elo: 1500, wins: 1, losses: 1, games: 2, win_rate: 0.5,
      }],
    });
    render(<MemoryRouter><Stats auth={{ token: 'token', profile: { user_id: 'u1' } }} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('tab', { name: 'duos' }));

    expect(await screen.findByRole('region', { name: 'Duo stats' })).toBeInTheDocument();
    expect(screen.getByText('#1 DUO')).toBeInTheDocument();
    expect(screen.getByText('Bravo + Charlie')).toBeInTheDocument();
    expect(screen.getByText('2 of 3 games')).toBeInTheDocument();
    expect(screen.getByText('RANKED BY ELO')).toBeInTheDocument();
  });

  it('shows every duo tied for first instead of choosing one', async () => {
    mocks.getDuoLadder.mockResolvedValue({
      ranked: [
        { duo_id: 'a', members: profiles, elo: 1540, wins: 4, losses: 1, games: 5, win_rate: 0.8, rank: 1 },
        { duo_id: 'b', members: [{ user_id: 'u3', display_name: 'Charlie' }, { user_id: 'u4', display_name: 'Delta' }], elo: 1590, wins: 3, losses: 0, games: 3, win_rate: 1, rank: 1 },
        { duo_id: 'c', members: [{ user_id: 'u5', display_name: 'Echo' }, { user_id: 'u6', display_name: 'Foxtrot' }], elo: 1510, wins: 3, losses: 2, games: 5, win_rate: 0.6, rank: 3 },
      ],
      to_watch: [],
    });
    render(<MemoryRouter><Stats auth={{ token: 'token', profile: { user_id: 'u1' } }} /></MemoryRouter>);
    fireEvent.click(screen.getByRole('tab', { name: 'duos' }));

    expect(await screen.findByLabelText('2 duos tied for first')).toBeInTheDocument();
    expect(screen.getByText('Alpha + Bravo')).toBeInTheDocument();
    expect(screen.getByText('Charlie + Delta')).toBeInTheDocument();
    expect(screen.getByText('3')).toBeInTheDocument();
  });

  it('does not request private duo data for an anonymous Stats visit', async () => {
    render(<MemoryRouter initialEntries={['/?view=duos']}><Stats auth={{ token: null, profile: null }} /></MemoryRouter>);

    expect(await screen.findByText('Sign in with a registered Dice profile to view duo ratings.')).toBeInTheDocument();
    expect(mocks.getDuoLadder).not.toHaveBeenCalled();
  });
});
