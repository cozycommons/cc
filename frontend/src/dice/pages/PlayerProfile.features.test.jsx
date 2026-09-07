import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getProfile: vi.fn(),
  getProfileGames: vi.fn(),
  getRatingProgress: vi.fn(),
}));

vi.mock('../../contexts/SupabaseContext', () => ({
  useSupabase: () => ({ supabase: null }),
}));
vi.mock('../api.js', () => ({
  diceApi: {
    getProfile: mocks.getProfile,
    getProfileGames: mocks.getProfileGames,
    getRatingProgress: mocks.getRatingProgress,
  },
}));
vi.mock('../components/PlayerAvatar.jsx', () => ({ default: () => <div>avatar</div> }));
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

function renderProfile({ viewedUserId = 'u1', state, updateFeature = vi.fn(), progress, games = [] }) {
  const auth = {
    user: { id: 'u1', email: 'player@example.com' },
    token: 'token',
    features: { dice_live_referee: state },
    isAdmin: false,
    refreshProfile: vi.fn(),
    updateFeature,
    signOut: vi.fn(),
  };
  mocks.getProfile.mockResolvedValue(profile(viewedUserId));
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
  return { updateFeature };
}

describe('PlayerProfile experimental features', () => {
  afterEach(() => vi.clearAllMocks());

  it('shows profile access as the sole availability state', async () => {
    renderProfile({ state: { opted_in: true, effective: true } });

    expect(await screen.findByText('// EXPERIMENTAL FEATURES')).toBeInTheDocument();
    expect(screen.getByRole('checkbox', { name: /live referee beta/i })).toBeChecked();
    expect(screen.getByText('Enabled for your account.')).toBeInTheDocument();
  });

  it.each([
    { optedIn: false, nextValue: true },
    { optedIn: true, nextValue: false },
  ])('updates only the current user preference from $optedIn to $nextValue', async ({ optedIn, nextValue }) => {
    const updateFeature = vi.fn().mockResolvedValue({});
    renderProfile({ state: { opted_in: optedIn, effective: optedIn }, updateFeature });

    fireEvent.click(await screen.findByRole('checkbox', { name: /live referee beta/i }));

    await waitFor(() => {
      expect(updateFeature).toHaveBeenCalledWith('dice_live_referee', nextValue);
    });
  });

  it('shows availability when profile access is on', async () => {
    renderProfile({ state: { opted_in: true, effective: true } });

    expect(await screen.findByText('Enabled for your account.')).toBeInTheDocument();
    expect(screen.queryByText(/currently unavailable/i)).not.toBeInTheDocument();
  });

  it('does not show preference controls on another player public profile', async () => {
    renderProfile({ viewedUserId: 'u2', state: { opted_in: true, effective: true } });

    expect(await screen.findByText('Player u2')).toBeInTheDocument();
    expect(screen.queryByText('// EXPERIMENTAL FEATURES')).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox', { name: /live referee beta/i })).not.toBeInTheDocument();
  });

  it('shows authoritative rating progress and last-match meaning', async () => {
    renderProfile({ state: { opted_in: false, effective: false } });

    expect(await screen.findByText('2')).toBeInTheDocument();
    expect(screen.getByText('+18')).toBeInTheDocument();
    expect(screen.getByText('1542')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('Moved up 1 rank last match.');
  });

  it('shows a tied rank as the same plain rank number', async () => {
    renderProfile({
      state: { opted_in: false, effective: false },
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
      state: { opted_in: false, effective: false },
      games: [{ id: 'g1', players: [{ user_id: 'u1', elo_before: 1500, elo_after: 1518 }] }],
      progress: {
        current_rank: null, current_rank_tied: false, is_provisional: false,
        personal_best: 1507, last_delta: 7, last_rank_change: null,
        history: [{ game_id: 'g1', played_at: '2026-08-29T12:00:00Z', rating_after: 1507, delta: 7 }],
      },
    });

    expect(await screen.findByText('Hidden')).toBeInTheDocument();
    expect(screen.getByText('g1:7')).toBeInTheDocument();
  });
});
