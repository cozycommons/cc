import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getLiveGames: vi.fn(),
  searchProfiles: vi.fn(),
  createLiveGame: vi.fn(),
  joinLiveGame: vi.fn(),
  leaveLiveGame: vi.fn(),
}));
vi.mock('../api.js', () => ({ diceApi: mocks }));

import LiveLobby from './LiveLobby.jsx';

const game = {
  id: 'match-1234',
  team_order: ['blue', 'clay'],
  teams: { blue: ['alice', 'bea'], clay: ['cam', 'dev'] },
  score: [2, 1],
  status: 'active',
  version: 4,
  player_names: { alice: 'Alice', bea: 'Bea', cam: 'Cam', dev: 'Dev' },
  referees: [{ user_id: 'other', left_at: null }],
};

function renderLobby(effective = true) {
  const auth = {
    token: 'token',
    user: { id: 'me' },
    features: { dice_live_referee: { opted_in: effective, effective } },
  };
  return render(
    <MemoryRouter>
      <Routes>
        <Route path="/" element={<LiveLobby auth={auth} />} />
        <Route path="/dice/live/:matchId" element={<p>Referee screen</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

describe('LiveLobby', () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.clearAllMocks();
  });

  it('makes direct navigation clearly unavailable without a live request when disabled', () => {
    renderLobby(false);
    expect(screen.getByText('Live referee unavailable')).toBeInTheDocument();
    expect(mocks.getLiveGames).not.toHaveBeenCalled();
  });

  it('shows an ongoing 2v2 score and joined referees without internal version clutter', async () => {
    mocks.getLiveGames.mockResolvedValue([game]);
    renderLobby();

    expect(await screen.findByText('2–1')).toBeInTheDocument();
    expect(screen.getByText('Alice + Bea')).toBeInTheDocument();
    expect(screen.getByText('Live')).toBeInTheDocument();
    expect(screen.queryByText('v4')).not.toBeInTheDocument();
    expect(screen.getByText('1 referee joined')).toBeInTheDocument();
  });

  it('starts a live game from four registered players', async () => {
    mocks.getLiveGames.mockResolvedValue([]);
    mocks.searchProfiles.mockResolvedValue([
      { user_id: 'alice', display_name: 'Alice', elo_rating: 1500 },
      { user_id: 'bea', display_name: 'Bea', elo_rating: 1500 },
      { user_id: 'cam', display_name: 'Cam', elo_rating: 1500 },
      { user_id: 'dev', display_name: 'Dev', elo_rating: 1500 },
    ]);
    mocks.createLiveGame.mockResolvedValue({ id: 'new-match' });
    renderLobby();
    fireEvent.click(await screen.findByRole('button', { name: 'Start game' }));
    for (const name of ['Alice', 'Bea', 'Cam', 'Dev']) fireEvent.click(screen.getByRole('button', { name }));
    expect(screen.queryByRole('combobox')).not.toBeInTheDocument();
    expect(screen.queryByText('1500')).not.toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Start live game' }));
    await waitFor(() => expect(mocks.createLiveGame).toHaveBeenCalledWith('token', expect.objectContaining({
      team_order: ['blue', 'clay'], teams: { blue: ['alice', 'bea'], clay: ['cam', 'dev'] },
    })));
  });

  it('swaps filled player slots in one tap when the throwing order changes', async () => {
    mocks.getLiveGames.mockResolvedValue([]);
    mocks.searchProfiles.mockResolvedValue([
      { user_id: 'alice', display_name: 'Alice', elo_rating: 1500 },
      { user_id: 'bea', display_name: 'Bea', elo_rating: 1500 },
      { user_id: 'cam', display_name: 'Cam', elo_rating: 1500 },
      { user_id: 'dev', display_name: 'Dev', elo_rating: 1500 },
    ]);
    renderLobby();
    fireEvent.click(await screen.findByRole('button', { name: 'Start game' }));
    for (const name of ['Alice', 'Bea', 'Cam', 'Dev']) fireEvent.click(screen.getByRole('button', { name }));

    fireEvent.click(screen.getByRole('button', { name: 'Team 1 1st thrower: Alice' }));
    fireEvent.click(screen.getByRole('button', { name: 'Bea' }));
    expect(screen.getByRole('button', { name: 'Team 1 1st thrower: Bea' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Team 1 2nd thrower: Alice' })).toBeInTheDocument();
    const order = within(screen.getByRole('region', { name: 'Throw order' }))
      .getAllByRole('listitem').map((item) => item.getAttribute('aria-label'));
    expect(order).toEqual(['1: Bea', '2: Alice', '3: Cam', '4: Dev']);
  });

  it('distinguishes UUID players that share the same leading segment', async () => {
    mocks.getLiveGames.mockResolvedValue([{ ...game, teams: {
      blue: ['10000000-0000-0000-0000-000000000002', '10000000-0000-0000-0000-000000000003'],
      clay: ['10000000-0000-0000-0000-000000000004', '10000000-0000-0000-0000-000000000005'],
    } }]);
    renderLobby();
    expect(await screen.findByText('0002 + 0003')).toBeInTheDocument();
    expect(screen.getByText('0004 + 0005')).toBeInTheDocument();
  });

  it('joins and opens the referee screen in one step', async () => {
    mocks.getLiveGames.mockResolvedValue([game]);
    mocks.joinLiveGame.mockResolvedValue({ joined: true });
    renderLobby();

    fireEvent.click(await screen.findByRole('button', { name: 'Join & referee' }));
    await waitFor(() => expect(mocks.joinLiveGame).toHaveBeenCalledWith('token', game.id));
    expect(await screen.findByText('Referee screen')).toBeInTheDocument();
    expect(mocks.getLiveGames).toHaveBeenCalledTimes(1);
  });

  it('lets a joined referee leave and reloads canonical membership', async () => {
    const joinedGame = { ...game, referees: [...game.referees, { user_id: 'me', left_at: null }] };
    mocks.getLiveGames.mockResolvedValueOnce([joinedGame]).mockResolvedValueOnce([game]);
    mocks.leaveLiveGame.mockResolvedValue({ joined: false });
    renderLobby();

    fireEvent.click(await screen.findByRole('button', { name: 'Leave' }));
    await waitFor(() => expect(mocks.leaveLiveGame).toHaveBeenCalledWith('token', game.id));
    expect(mocks.getLiveGames).toHaveBeenCalledTimes(2);
  });

  it('keeps usable games visible when a background refresh fails', async () => {
    vi.useFakeTimers();
    mocks.getLiveGames.mockResolvedValueOnce([game]).mockRejectedValueOnce(new Error('Failed to fetch'));
    renderLobby();
    await act(async () => {});
    expect(screen.getByText('2–1')).toBeInTheDocument();

    await act(async () => { vi.advanceTimersByTime(15000); });
    await act(async () => {});
    expect(mocks.getLiveGames).toHaveBeenCalledTimes(2);
    expect(screen.getByText('2–1')).toBeInTheDocument();
    expect(screen.getByText('Showing the last update.')).toBeInTheDocument();
    expect(screen.queryByText('Failed to fetch')).not.toBeInTheDocument();
  });

  it('refreshes ongoing games every 15 seconds and cleans up on unmount', async () => {
    vi.useFakeTimers();
    mocks.getLiveGames.mockResolvedValue([game]);
    const view = renderLobby();
    await act(async () => {});
    expect(mocks.getLiveGames).toHaveBeenCalledTimes(1);
    await act(async () => { vi.advanceTimersByTime(15000); });
    await act(async () => {});
    expect(mocks.getLiveGames).toHaveBeenCalledTimes(2);
    view.unmount();
    await act(async () => { vi.advanceTimersByTime(30000); });
    expect(mocks.getLiveGames).toHaveBeenCalledTimes(2);
  });

  it('explains player-list failures and lets the referee retry before starting', async () => {
    mocks.getLiveGames.mockResolvedValue([]);
    mocks.searchProfiles
      .mockRejectedValueOnce(new Error('Player directory is offline'))
      .mockResolvedValueOnce([
        { user_id: 'alice', display_name: 'Alice', elo_rating: 1500 },
        { user_id: 'bea', display_name: 'Bea', elo_rating: 1500 },
        { user_id: 'cam', display_name: 'Cam', elo_rating: 1500 },
        { user_id: 'dev', display_name: 'Dev', elo_rating: 1500 },
      ]);
    renderLobby();
    fireEvent.click(await screen.findByRole('button', { name: 'Start game' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('Player directory is offline');
    expect(screen.getByRole('button', { name: 'Start live game' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getByRole('button', { name: 'Alice' })).toBeEnabled());
    expect(screen.getByRole('button', { name: 'Start live game' })).toBeDisabled();
    expect(screen.getByRole('group', { name: 'TEAM 1' })).toBeInTheDocument();
  });
});
