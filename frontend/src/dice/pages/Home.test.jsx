import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getGames: vi.fn(),
  getEloLeaderboard: vi.fn(),
  getSinkLeaderboard: vi.fn(),
  getSelfSinkLeaderboard: vi.fn(),
  getTournaments: vi.fn(),
  getLiveGames: vi.fn(),
  getLivePrediction: vi.fn(),
}));

vi.mock('../api.js', () => ({ diceApi: mocks }));
vi.mock('../../analytics/usePageviewTracking', () => ({ usePageviewTracking: vi.fn() }));
vi.mock('../components/PhotoGallery.jsx', () => ({ default: () => <div>Photo gallery</div> }));
vi.mock('../components/GameRow.jsx', () => ({ default: ({ game }) => <div>Game {game.id}</div> }));
vi.mock('../components/LeaderboardRow.jsx', () => ({
  default: ({ profile, rank, isCurrentUser, barMode }) => (
    <div data-rank={rank ?? ''} data-current-user={isCurrentUser ? 'true' : 'false'} data-bar-mode={barMode}>{profile.display_name}</div>
  ),
}));
vi.mock('../components/TournamentRow.jsx', () => ({ default: ({ tournament }) => <div>Tournament {tournament.name}</div> }));
vi.mock('../components/PlayerAvatar.jsx', () => ({ default: () => <span>Avatar</span> }));

import Home, { calculateStreaks, calculateSynergies, matchStory, splitTournaments } from './Home.jsx';

const disabledAuth = {
  token: 'token',
  user: { id: 'u1' },
  features: { dice_live_referee: { opted_in: false, effective: false } },
};
const enabledAuth = {
  ...disabledAuth,
  features: { dice_live_referee: { opted_in: true, effective: true } },
};

function arrange({ tournaments = [], liveGames = [], elo = [], sinks = [], selfSinks = [] } = {}) {
  mocks.getGames.mockResolvedValue([{ id: 'recent-1' }]);
  mocks.getEloLeaderboard.mockResolvedValue(elo);
  mocks.getSinkLeaderboard.mockResolvedValue(sinks);
  mocks.getSelfSinkLeaderboard.mockResolvedValue(selfSinks);
  mocks.getTournaments.mockResolvedValue(tournaments);
  mocks.getLiveGames.mockResolvedValue(liveGames);
  mocks.getLivePrediction.mockResolvedValue({ status: 'available', match_version: 1, team1_win_probability: 0.55, team2_win_probability: 0.45 });
}

function renderHome(auth) {
  return render(<MemoryRouter><Home auth={auth} /></MemoryRouter>);
}

describe('Dice home dashboard', () => {
  afterEach(() => vi.clearAllMocks());

  it('waits for feature hydration before choosing a homepage', () => {
    arrange();
    renderHome({ ...disabledAuth, loading: true });

    expect(screen.getByText('Loading…')).toBeInTheDocument();
    expect(mocks.getGames).not.toHaveBeenCalled();
    expect(mocks.getLiveGames).not.toHaveBeenCalled();
  });

  it('partitions and orders tournaments around the current time', () => {
    const result = splitTournaments([
      { id: 'past-old', starts_at: '2026-08-01T12:00:00Z' },
      { id: 'future-late', starts_at: '2026-09-10T12:00:00Z' },
      { id: 'invalid', starts_at: 'not-a-date' },
      { id: 'past-recent', starts_at: '2026-08-08T12:00:00Z' },
      { id: 'future-next', starts_at: '2026-09-01T12:00:00Z' },
    ], Date.parse('2026-08-27T00:00:00Z'));

    expect(result.upcoming.map((item) => item.id)).toEqual(['future-next', 'future-late']);
    expect(result.past.map((item) => item.id)).toEqual(['past-recent', 'past-old']);
  });

  it('turns match data into a concise, factual story', () => {
    expect(matchStory({
      ranked: true,
      team1_score: 11,
      team2_score: 9,
      players: [{ display_name: 'Jaycee', self_sinks: 0, elo_before: 1400, elo_after: 1418 }],
    })).toBe('Jaycee +18 ELO');
    expect(matchStory({
      ranked: false,
      team1_score: 11,
      team2_score: 8,
      players: [{ display_name: 'Charlie', self_sinks: 2 }],
    })).toBe('2 self-sinks');
  });

  it('calculates current and best win streaks from match history', () => {
    const games = [
      { played_at: '2026-08-20', winner_team: 1, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }] },
      { played_at: '2026-08-21', winner_team: 1, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }] },
      { played_at: '2026-08-22', winner_team: 2, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }] },
      { played_at: '2026-08-23', winner_team: 1, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }] },
    ];
    expect(calculateStreaks(games)).toEqual([{ user_id: 'u1', display_name: 'Jason', current: 1, best: 2, latest: true }]);
  });

  it('ranks teammate pairings by their combined record', () => {
    const games = [
      { winner_team: 1, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }, { user_id: 'u2', display_name: 'Jaycee', team: 1 }] },
      { winner_team: 2, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }, { user_id: 'u2', display_name: 'Jaycee', team: 1 }] },
      { winner_team: 1, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }, { user_id: 'u2', display_name: 'Jaycee', team: 1 }] },
    ];
    expect(calculateSynergies(games)[0]).toMatchObject({ players: ['Jason', 'Jaycee'], wins: 2, losses: 1 });
  });

  it('puts live activity first for an enabled profile', async () => {
    arrange({
      tournaments: [
        { id: 'past', name: 'August 8', starts_at: '2020-08-08T12:00:00Z' },
        { id: 'future', name: 'Next Tournament', starts_at: '2099-09-01T12:00:00Z' },
      ],
      liveGames: [{
        id: 'live-1',
        version: 1,
        created_at: new Date().toISOString(),
        team_order: ['blue', 'clay'],
        teams: { blue: ['u1', 'u2'], clay: ['u3', 'u4'] },
        player_names: { u1: 'Jason', u2: 'Andrew', u3: 'Jaycee', u4: 'Warner' },
        player_stats: {
          u1: { elo_rating: 1500, sinks: 4 }, u2: { elo_rating: 1600, sinks: 6 },
          u3: { elo_rating: 1450, sinks: 3 }, u4: { elo_rating: 1550, sinks: 2 },
        },
        score: [3, 2],
        referees: [{ user_id: 'u1', left_at: null }],
      }],
    });
    const { container } = renderHome(enabledAuth);

    expect(await screen.findByText('// LIVE GAMES')).toBeInTheDocument();
    expect(screen.getByText('3–2')).toBeInTheDocument();
    expect(screen.getByText('Refereeing')).toBeInTheDocument();
    expect(screen.getByText(/● Live · 0:0\d/)).toBeInTheDocument();
    expect(screen.getByText('1550 ELO · 10 sinks')).toBeInTheDocument();
    expect(screen.getByText('1500 ELO · 5 sinks')).toBeInTheDocument();
    expect(await screen.findByLabelText('Live probability 55 percent to 45 percent')).toBeInTheDocument();
    expect(mocks.getLiveGames).toHaveBeenCalledWith('token');

    await screen.findByText('Tournament Next Tournament');
    const pageText = container.textContent;
    expect(pageText.indexOf('// LIVE GAMES')).toBeLessThan(pageText.indexOf('// RECENT MATCHES'));
    expect(pageText.indexOf('// RECENT MATCHES')).toBeLessThan(pageText.indexOf('// TOURNAMENTS'));
  });

  it('does not reserve homepage space when there are no live games', async () => {
    arrange();
    renderHome(enabledAuth);

    await waitFor(() => expect(mocks.getLiveGames).toHaveBeenCalledWith('token'));
    expect(screen.queryByText('// LIVE GAMES')).not.toBeInTheDocument();
  });

  it('keeps the latest champion visible when no future tournament is scheduled', async () => {
    arrange({
      tournaments: [{
        id: 'past',
        name: 'Local Spring Classic',
        starts_at: '2020-08-08T12:00:00Z',
        bracket: { champion: [
          { user_id: 'u2', display_name: 'Echo Ace' },
          { user_id: 'u3', display_name: 'Hotel Hop' },
        ] },
      }],
    });
    renderHome(enabledAuth);

    expect(await screen.findByText('LATEST CHAMPIONS')).toBeInTheDocument();
    expect(screen.getByText('Echo Ace + Hotel Hop')).toBeInTheDocument();
    expect(screen.getByText(/Local Spring Classic/)).toBeInTheDocument();
  });

  it('keeps sink and self-sink leaders visible beside ELO standings', async () => {
    arrange({
      elo: [{ user_id: 'u1', display_name: 'ELO Friend', elo_rating: 1510 }],
      sinks: [{ user_id: 'u2', display_name: 'Sink Friend', sinks: 7 }],
      selfSinks: [{ user_id: 'u3', display_name: 'Self-sink Friend', self_sinks: 3 }],
    });
    renderHome(enabledAuth);

    expect(await screen.findByText('ELO Friend')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /Sink Friend/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Self-sinks' }));
    expect(screen.getByRole('link', { name: /Self-sink Friend/ })).toBeInTheDocument();
    expect(screen.getByText('// ELO STANDINGS')).toBeInTheDocument();
    expect(screen.getByText('// SINK LEADERS')).toBeInTheDocument();
    expect(screen.queryByText('// RECORDS')).not.toBeInTheDocument();
  });

  it('shows the top three and pins the signed-in player outside them', async () => {
    const elo = [
      { user_id: 'u2', display_name: 'First', elo_rating: 1600 },
      { user_id: 'u3', display_name: 'Second', elo_rating: 1580 },
      { user_id: 'u4', display_name: 'Third', elo_rating: 1560 },
      { user_id: 'u1', display_name: 'Me', elo_rating: 1490 },
    ];
    arrange({ elo });
    renderHome(enabledAuth);

    const me = await screen.findByText('Me');
    expect(me).toHaveAttribute('data-rank', '4');
    expect(me).toHaveAttribute('data-current-user', 'true');
    expect(me).toHaveAttribute('data-bar-mode', 'elo');
    expect(mocks.getEloLeaderboard).toHaveBeenCalledWith(500, true);
    expect(mocks.getSinkLeaderboard).toHaveBeenCalledWith(500, false);
    expect(mocks.getSelfSinkLeaderboard).toHaveBeenCalledWith(500, false);
  });

  it('preserves the production homepage and avoids experimental requests for a disabled profile', async () => {
    arrange({ tournaments: [{ id: 'past', name: 'August 8', starts_at: '2020-08-08T12:00:00Z' }] });
    renderHome(disabledAuth);

    await waitFor(() => expect(screen.getByText('Game recent-1')).toBeInTheDocument());
    expect(mocks.getLiveGames).not.toHaveBeenCalled();
    expect(screen.queryByText('// LIVE GAMES')).not.toBeInTheDocument();
    expect(screen.getByText('// TOURNAMENTS')).toBeInTheDocument();
    expect(screen.getByText('Tournament August 8')).toBeInTheDocument();
    expect(screen.getByText('// ELO LEADERBOARD')).toBeInTheDocument();
    expect(screen.queryByText('// ELO STANDINGS')).not.toBeInTheDocument();
    expect(screen.queryByText('// SINK LEADERS')).not.toBeInTheDocument();
    expect(mocks.getGames).toHaveBeenCalledWith(5);
    expect(mocks.getEloLeaderboard).toHaveBeenCalledWith(5);
    expect(mocks.getSinkLeaderboard).toHaveBeenCalledWith(5, true);
    expect(mocks.getSelfSinkLeaderboard).toHaveBeenCalledWith(5, true);
  });
});
