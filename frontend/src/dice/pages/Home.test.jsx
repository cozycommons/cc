import React from 'react';
import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
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
  getDuoLadder: vi.fn(),
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
vi.mock('../components/PlayerAvatar.jsx', () => ({ default: ({ profile }) => <span>{profile.display_name} avatar</span> }));

import Home, { calculateStreaks, calculateSynergies, matchStory, splitTournaments } from './Home.jsx';

const releasedAuth = {
  token: 'token',
  user: { id: 'u1' },
  profile: { user_id: 'u1', display_name: 'Player' },
};
const staleOptOutAuth = {
  ...releasedAuth,
  features: { dice_live_referee: { opted_in: false, effective: false } },
};

function arrange({ games = [{ id: 'recent-1' }], tournaments = [], liveGames = [], elo = [], sinks = [], selfSinks = [], duos = { ranked: [], to_watch: [] } } = {}) {
  mocks.getGames.mockResolvedValue(games);
  mocks.getEloLeaderboard.mockResolvedValue(elo);
  mocks.getSinkLeaderboard.mockResolvedValue(sinks);
  mocks.getSelfSinkLeaderboard.mockResolvedValue(selfSinks);
  mocks.getTournaments.mockResolvedValue(tournaments);
  mocks.getLiveGames.mockResolvedValue(liveGames);
  mocks.getLivePrediction.mockResolvedValue({ status: 'available', match_version: 1, team1_win_probability: 0.55, team2_win_probability: 0.45 });
  mocks.getDuoLadder.mockResolvedValue(duos);
}

function renderHome(auth) {
  return render(<MemoryRouter><Home auth={auth} /></MemoryRouter>);
}

describe('Dice home dashboard', () => {
  afterEach(() => vi.clearAllMocks());

  it('waits for authentication hydration before loading the homepage', () => {
    arrange();
    renderHome({ ...releasedAuth, loading: true });

    expect(screen.getByText('Loading…')).toBeInTheDocument();
    expect(mocks.getGames).not.toHaveBeenCalled();
    expect(mocks.getLiveGames).not.toHaveBeenCalled();
  });

  it('does not request private home data without a registered profile', async () => {
    arrange();
    renderHome({ ...releasedAuth, profile: null, loading: false });

    await waitFor(() => expect(mocks.getGames).toHaveBeenCalled());
    expect(mocks.getLiveGames).not.toHaveBeenCalled();
    expect(mocks.getDuoLadder).not.toHaveBeenCalled();
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

  it('keeps the tournament directory visible when no tournament is scheduled', async () => {
    arrange({ tournaments: [] });
    renderHome(releasedAuth);

    const emptyLink = await screen.findByRole('link', { name: 'Browse tournament history →' });
    const section = emptyLink.closest('section');
    expect(within(section).getByRole('link', { name: 'View all →' })).toHaveAttribute('href', '/dice/tournaments');
    expect(emptyLink).toHaveAttribute('href', '/dice/tournaments');
  });

  it('turns match data into a concise, factual story', () => {
    expect(matchStory({
      ranked: true,
      team1_score: 11,
      team2_score: 9,
      players: [
        { display_name: 'Jaycee', self_sinks: 0, elo_before: 1400, elo_after: 1418 },
        { display_name: 'Charlie', self_sinks: 0, elo_before: 1500, elo_after: 1518 },
      ],
    })).toBeNull();
    expect(matchStory({
      ranked: false,
      team1_score: 11,
      team2_score: 8,
      players: [
        { display_name: 'Charlie', sinks: 2, self_sinks: 1 },
        { display_name: 'Jaycee', sinks: 1, self_sinks: 1 },
      ],
    })).toBe('3 sinks · 2 self-sinks');
  });

  it('calculates current and best win streaks from match history', () => {
    const games = [
      { id: 'g1', ranked: true, played_at: '2026-08-20', winner_team: 1, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }] },
      { id: 'g2', ranked: true, played_at: '2026-08-21', winner_team: 1, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }] },
      { id: 'g3', ranked: true, played_at: '2026-08-22', winner_team: 2, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }] },
      { id: 'g4', ranked: true, played_at: '2026-08-23', winner_team: 1, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }] },
    ];
    expect(calculateStreaks(games)).toEqual([{ user_id: 'u1', display_name: 'Jason', current: 1, best: 2, latest: true, current_game_ids: ['g4'], best_game_ids: ['g1', 'g2'] }]);
  });

  it('ignores unranked games without interrupting a ranked win streak', () => {
    const games = [
      { id: 'g1', ranked: true, played_at: '2026-08-20', winner_team: 1, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }] },
      { id: 'casual', ranked: false, played_at: '2026-08-21', winner_team: 2, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }] },
      { id: 'g2', ranked: true, played_at: '2026-08-22', winner_team: 1, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }] },
    ];
    expect(calculateStreaks(games)[0]).toMatchObject({
      current: 2,
      best: 2,
      current_game_ids: ['g1', 'g2'],
      best_game_ids: ['g1', 'g2'],
    });
  });

  it('does not create a streak from only unranked games', () => {
    const games = [
      { id: 'g1', ranked: false, played_at: '2026-08-20', winner_team: 1, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }] },
      { id: 'g2', ranked: false, played_at: '2026-08-21', winner_team: 1, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }] },
    ];
    expect(calculateStreaks(games)).toEqual([]);
  });

  it('keeps duo-only matches out of individual streaks', () => {
    const games = [
      { id: 'g1', ranked: true, duo_only: true, played_at: '2026-08-20', winner_team: 1, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }] },
      { id: 'g2', ranked: true, played_at: '2026-08-21', winner_team: 1, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }] },
    ];
    expect(calculateStreaks(games)).toEqual([]);
  });

  it('shows player identity and sends the streak preview to the streaks view', async () => {
    arrange({ games: [
      { id: 'g1', ranked: true, played_at: '2026-08-20', winner_team: 1, players: [{ user_id: 'u1', display_name: 'Jason', avatar_url: '/jason.webp', team: 1 }] },
      { id: 'g2', ranked: true, played_at: '2026-08-21', winner_team: 1, players: [{ user_id: 'u1', display_name: 'Jason', avatar_url: '/jason.webp', team: 1 }] },
    ] });
    renderHome(releasedAuth);

    const streak = (await screen.findByText('CURRENT STREAK')).closest('a');
    expect(streak).toHaveAttribute('href', '/dice/stats/streaks/u1');
    expect(within(streak).getByText('Jason avatar')).toBeInTheDocument();
    expect(within(streak).getByText('2')).toBeInTheDocument();
    expect(within(streak.closest('section')).getByRole('link', { name: 'View all →' })).toHaveAttribute('href', '/dice/stats?view=streaks');
  });

  it('ranks teammate pairings by their combined record', () => {
    const games = [
      { winner_team: 1, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }, { user_id: 'u2', display_name: 'Jaycee', team: 1 }] },
      { winner_team: 2, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }, { user_id: 'u2', display_name: 'Jaycee', team: 1 }] },
      { winner_team: 1, players: [{ user_id: 'u1', display_name: 'Jason', team: 1 }, { user_id: 'u2', display_name: 'Jaycee', team: 1 }] },
    ];
    expect(calculateSynergies(games)[0]).toMatchObject({ players: ['Jason', 'Jaycee'], wins: 2, losses: 1 });
  });

  it('puts live activity first for a signed-in profile', async () => {
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
    const { container } = renderHome(releasedAuth);

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
    let resolveLiveGames;
    mocks.getLiveGames.mockImplementation(() => new Promise((resolve) => {
      resolveLiveGames = resolve;
    }));
    renderHome(releasedAuth);

    await waitFor(() => expect(mocks.getLiveGames).toHaveBeenCalledWith('token'));
    await act(async () => resolveLiveGames([]));
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
    renderHome(releasedAuth);

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
    renderHome(releasedAuth);

    expect(await screen.findByText('ELO Friend')).toBeInTheDocument();
    expect(await screen.findByRole('link', { name: /Sink Friend/ })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Self-sinks' }));
    expect(await screen.findByRole('link', { name: /Self-sink Friend/ })).toBeInTheDocument();
    expect(screen.getByText('// ELO STANDINGS')).toBeInTheDocument();
    expect(screen.getByText('// SINK LEADERS')).toBeInTheDocument();
    expect(screen.queryByText('// RECORDS')).not.toBeInTheDocument();
  });

  it('shows only three-game-qualified duos in the compact homepage preview', async () => {
    arrange({
      duos: {
        ranked: [{
          duo_id: '2:u12:u2',
          members: [{ user_id: 'u1', display_name: 'Qualified Alpha' }, { user_id: 'u2', display_name: 'Qualified Bravo' }],
          elo: 1600,
          wins: 2,
          losses: 1,
          games: 3,
          homepage_eligible: true,
        }],
        to_watch: [{
          duo_id: '2:u32:u4',
          members: [{ user_id: 'u3', display_name: 'Provisional Charlie' }, { user_id: 'u4', display_name: 'Provisional Delta' }],
          elo: 1500,
          wins: 2,
          losses: 0,
          games: 2,
          homepage_eligible: false,
        }],
      },
    });
    renderHome(releasedAuth);

    expect(await screen.findByText('Qualified Alpha + Qualified Bravo')).toBeInTheDocument();
    expect(screen.getByText('// TOP DUOS')).toBeInTheDocument();
    expect(screen.queryByText('Provisional Charlie + Provisional Delta')).not.toBeInTheDocument();
    expect(mocks.getDuoLadder).toHaveBeenCalledWith('token', 3, true);
  });

  it('shows the top three and pins the signed-in player outside them', async () => {
    const elo = [
      { user_id: 'u2', display_name: 'First', elo_rating: 1600 },
      { user_id: 'u3', display_name: 'Second', elo_rating: 1580 },
      { user_id: 'u4', display_name: 'Third', elo_rating: 1560 },
      { user_id: 'u1', display_name: 'Me', elo_rating: 1490 },
    ];
    arrange({ elo });
    renderHome(releasedAuth);

    const me = await screen.findByText('Me');
    expect(me).toHaveAttribute('data-rank', '4');
    expect(me).toHaveAttribute('data-current-user', 'true');
    expect(me).not.toHaveAttribute('data-bar-mode');
    expect(mocks.getEloLeaderboard).toHaveBeenCalledWith(500, true);
    expect(mocks.getSinkLeaderboard).toHaveBeenCalledWith(500, false);
    expect(mocks.getSelfSinkLeaderboard).toHaveBeenCalledWith(500, false);
  });

  it('ignores a stale opt-out and renders only the released homepage', async () => {
    arrange({ tournaments: [{ id: 'future', name: 'Next Tournament', starts_at: '2099-08-08T12:00:00Z' }] });
    let resolveLiveGames;
    mocks.getLiveGames.mockImplementation(() => new Promise((resolve) => {
      resolveLiveGames = resolve;
    }));
    renderHome(staleOptOutAuth);

    await screen.findByText('Game recent-1');
    await screen.findByText('Tournament Next Tournament');
    expect(mocks.getLiveGames).toHaveBeenCalledWith('token');
    await act(async () => resolveLiveGames([]));
    expect(screen.queryByText('// LIVE GAMES')).not.toBeInTheDocument();
    expect(screen.getByText('// TOURNAMENTS')).toBeInTheDocument();
    expect(screen.getByText('// ELO STANDINGS')).toBeInTheDocument();
    expect(screen.getByText('// SINK LEADERS')).toBeInTheDocument();
    expect(mocks.getEloLeaderboard).toHaveBeenCalledWith(500, true);
    expect(mocks.getSinkLeaderboard).toHaveBeenCalledWith(500, false);
    expect(mocks.getSelfSinkLeaderboard).toHaveBeenCalledWith(500, false);
  });
});
