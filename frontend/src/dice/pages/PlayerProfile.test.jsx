import { render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getProfile: vi.fn(),
  getProfileGames: vi.fn(),
  getRatingProgress: vi.fn(),
  getBestPartner: vi.fn().mockResolvedValue(null),
}));

vi.mock('../../contexts/SupabaseContext', () => ({
  useSupabase: () => ({ supabase: null }),
}));
vi.mock('../api.js', () => ({
  diceApi: {
    getProfile: mocks.getProfile,
    getProfileGames: mocks.getProfileGames,
    getRatingProgress: mocks.getRatingProgress,
    getBestPartner: mocks.getBestPartner,
  },
}));
vi.mock('../components/PlayerAvatar.jsx', () => ({ default: ({ profile, size }) => <div data-size={size}>{profile.display_name} avatar</div> }));
vi.mock('../components/GameRow.jsx', () => ({
  default: ({ game, ratingDelta }) => <div>{game.id}:{String(ratingDelta)}</div>,
}));
vi.mock('../components/EloHistoryChart.jsx', () => ({ default: () => <div>chart</div> }));

import PlayerProfile from './PlayerProfile.jsx';

function profile(userId) {
  return {
    user_id: userId,
    display_name: `Player ${userId}`,
    elo_rating: 1500,
    games_played: 0,
    ranked_wins: 0,
    ranked_losses: 0,
    normal_wins: 0,
    normal_losses: 0,
    sinks: 0,
    self_sinks: 0,
    hide_from_leaderboard: false,
    sms_notifications_enabled: false,
    is_provisional: false,
  };
}

function renderProfile({ viewedUserId = 'u1', progress, games = [], headToHead = null }) {
  const auth = {
    user: { id: 'u1', email: 'player@example.com' },
    token: 'token',
    isAdmin: false,
    profile: { user_id: 'u1' },
    refreshProfile: vi.fn(),
    signOut: vi.fn(),
  };
  mocks.getProfile.mockResolvedValue({ ...profile(viewedUserId), head_to_head: headToHead });
  mocks.getProfileGames.mockResolvedValue(games);
  mocks.getRatingProgress.mockResolvedValue(progress ?? {
    current_rank: 2,
    current_rank_tied: false,
    is_provisional: false,
    personal_best: 1542,
    last_delta: 18,
    last_rank_change: 1,
    history: [],
  });

  render(
    <MemoryRouter initialEntries={[`/dice/profile/${viewedUserId}`]}>
      <Routes>
        <Route path="/dice/profile/:userId" element={<PlayerProfile auth={auth} />} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('PlayerProfile released experience', () => {
  afterEach(() => vi.clearAllMocks());

  it('does not expose the retired experience preference', async () => {
    renderProfile({ viewedUserId: 'u2' });

    expect(await screen.findByText('Player u2')).toBeInTheDocument();
    expect(screen.queryByText('// DICE EXPERIENCE')).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: /live referee experience/i })).not.toBeInTheDocument();
  });

  it('shows authoritative rating progress and last-match meaning', async () => {
    renderProfile({});

    expect(await screen.findByText('2')).toBeInTheDocument();
    expect(screen.getByText('+18')).toBeInTheDocument();
    expect(screen.getByText('1542')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Moved up 1 rank last match.');
  });

  it('shows a tied rank as the same plain rank number', async () => {
    renderProfile({
      progress: {
        current_rank: 1, current_rank_tied: true, is_provisional: false,
        personal_best: 1542, last_delta: 18, last_rank_change: null, history: [],
      },
    });

    const progress = await screen.findByLabelText('Rating progress');
    expect(within(progress).getByText('1')).toBeInTheDocument();
    expect(within(progress).queryByText('T-1')).not.toBeInTheDocument();
  });

  it('labels an established private player as hidden and uses authoritative row deltas', async () => {
    renderProfile({
      games: [{ id: 'g1', players: [{ user_id: 'u1', elo_before: 1500, elo_after: 1518 }] }],
      progress: {
        current_rank: null, current_rank_tied: false, is_provisional: false,
        personal_best: 1507, last_delta: 7, last_rank_change: null,
        history: [{ game_id: 'g1', played_at: '2026-08-29T12:00:00Z', rating_after: 1507, delta: 7 }],
      },
    });

    expect(await screen.findByText('Hidden')).toBeInTheDocument();
    expect(await screen.findByText('g1:7')).toBeInTheDocument();
  });

  it('shows the player recorded-play sample from canonical game snapshots', async () => {
    renderProfile({
      state: { opted_in: true, effective: true },
      games: [{
        id: 'g1',
        players: [{ user_id: 'u1', display_name: 'Player u1', team: 1 }],
        recorded_stats: {
          coverage: 'partial', observations: 6,
          players: { u1: { outcomes: { point: 2, caught: 2, miss: 2 }, table_catches: 1, fifa_saves: 1 } },
        },
      }],
    });

    const recorded = await screen.findByRole('region', { name: 'Personal recorded play' });
    expect(within(recorded).getByText('67%')).toBeInTheDocument();
    expect(within(recorded).getByText('Missing plays are excluded, not counted as misses.')).toBeInTheDocument();
    expect(mocks.getProfileGames).toHaveBeenCalledWith('u1', 200);
  });
});


it.each([[20, 1, 10.5], [100, 100, 100.9], [1, 20, 10.5], null])('only shows a positive best partner (%s)', async (record) => {
  const [wins, losses, expectedWins] = record ?? [];
  mocks.getBestPartner.mockResolvedValue(record == null ? null : {
    duo_id: 'best:pair', members: [{ user_id: 'u1', display_name: 'Alpha' }, { user_id: 'u2', display_name: 'Bravo' }],
    synergy: { wins, losses, games: wins + losses, expected_wins: expectedWins, wins_above_expected: wins - expectedWins },
  });
  renderProfile({});
  await screen.findByText('Player u1');
  if (wins === 20) {
    expect(await screen.findByRole('link', { name: 'Best partner' })).toHaveAttribute('href', '/dice/stats/duos/best%3Apair');
    expect(screen.getByText('Bravo · 20–1 together')).toBeInTheDocument();
    expect(screen.getByText('95% wins, 50% expected')).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Best partner' });
    expect(within(link).getByText('Bravo avatar')).toHaveAttribute('data-size', '34');
    expect(within(link).getByText('→')).toBeInTheDocument();
  } else {
    expect(screen.queryByRole('link', { name: 'Best partner' })).not.toBeInTheDocument();
  }
  expect(screen.queryByText(/worst partner/i)).not.toBeInTheDocument();
  expect(mocks.getBestPartner).toHaveBeenCalledWith('token', 'u1');
});


it('keeps the partner row directly above head to head', async () => {
  mocks.getBestPartner.mockResolvedValue({ duo_id: 'best',
    members: [{ user_id: 'u1', display_name: 'Alpha' }, { user_id: 'u2', display_name: 'Bravo' }],
    synergy: { wins: 9, losses: 3, games: 12, expected_wins: 6, wins_above_expected: 3 } });
  renderProfile({ viewedUserId: 'u2', headToHead: { total_games: 1,
    opponent_wins: 1, opponent_losses: 0, teammate_wins: 0, teammate_losses: 0 } });
  const row = await screen.findByRole('link', { name: 'Best partner' });
  expect(row.nextElementSibling).toContainElement(screen.getByText('// HEAD TO HEAD'));
});
