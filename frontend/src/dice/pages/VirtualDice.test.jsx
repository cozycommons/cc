import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  openVirtualBankroll: vi.fn(),
  getVirtualMarkets: vi.fn(),
  getVirtualPicks: vi.fn(),
  getVirtualLeaderboard: vi.fn(),
  getLiveGames: vi.fn(),
  getLiveGame: vi.fn(),
  getTournament: vi.fn(),
  createVirtualMarket: vi.fn(),
  placeVirtualPick: vi.fn(),
}));
vi.mock('../api.js', () => ({ diceApi: mocks }));

import VirtualDice from './VirtualDice.jsx';

const auth = {
  token: 'token', user: { id: 'me' },
};
const game = {
  id: 'game-1', version: 0, status: 'active', team_order: ['blue', 'clay'],
  teams: { blue: ['alice', 'bea'], clay: ['cam', 'dev'] },
  player_names: { alice: 'Alice', bea: 'Bea', cam: 'Cam', dev: 'Dev' },
};
const market = {
  id: 4, live_match_id: game.id, status: 'open',
  selections: { blue: { probability_millionths: 600000 }, clay: { probability_millionths: 400000 } },
};
const tournament = { enrolled_players: ['alice', 'bea', 'cam', 'dev', 'me'].map((user_id) => ({ user_id })) };

function renderPage() {
  return render(
    <MemoryRouter initialEntries={['/dice/tournament/t1/virtual']}>
      <Routes><Route path="/dice/tournament/:tournamentId/virtual" element={<VirtualDice auth={auth} />} /></Routes>
    </MemoryRouter>,
  );
}

function ready({
  markets = [market], picks = [], liveGames = [game], balance = 1000,
  leaderboard = [
    { rank: 1, user_id: 'alice', display_name: 'Alice', balance: 1200 },
    { rank: 2, user_id: 'me', display_name: 'Referee', balance: 1000 },
  ],
} = {}) {
  mocks.openVirtualBankroll.mockResolvedValue({ balance });
  mocks.getVirtualMarkets.mockResolvedValue(markets);
  mocks.getVirtualPicks.mockResolvedValue(picks);
  mocks.getVirtualLeaderboard.mockResolvedValue(leaderboard);
  mocks.getLiveGames.mockResolvedValue(liveGames);
  mocks.getLiveGame.mockResolvedValue({ ...game, status: 'completed' });
  mocks.getTournament.mockResolvedValue(tournament);
  mocks.createVirtualMarket.mockResolvedValue(market);
  mocks.placeVirtualPick.mockImplementation((_token, _tournamentId, marketId, payload) => Promise.resolve({
    id: 8, market_id: marketId, selection: payload.selection, stake: payload.stake,
    potential_return: 416, status: 'open',
  }));
}

describe('VirtualDice', () => {
  afterEach(() => {
    vi.clearAllMocks();
    vi.useRealTimers();
  });

  it('shows bankroll and locked server odds, then places one clear pick', async () => {
    ready();
    renderPage();

    expect(await screen.findByText('1000')).toBeInTheDocument();
    expect(screen.getByText('60% chance')).toBeInTheDocument();
    expect(screen.getByText('Total return 166 Dice')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: 'Watch or referee this game' })).toHaveAttribute('href', '/dice/live/game-1');
    fireEvent.change(screen.getByLabelText('Stake'), { target: { value: '250' } });
    fireEvent.click(screen.getByRole('button', { name: /Alice \+ Bea/ }));

    await waitFor(() => expect(mocks.placeVirtualPick).toHaveBeenCalledWith('token', 't1', 4, expect.objectContaining({
      selection: 'blue', stake: 250,
    })));
    expect(await screen.findByText('250 on Alice + Bea')).toBeInTheDocument();
    expect(screen.queryByLabelText('Stake')).not.toBeInTheDocument();
  });

  it('shows authoritative tournament standings and identifies the current player', async () => {
    ready();
    renderPage();

    expect(await screen.findByRole('region', { name: 'TOURNAMENT STANDINGS' })).toHaveTextContent('#1Alice1200 Dice');
    expect(screen.getByRole('region', { name: 'TOURNAMENT STANDINGS' })).toHaveTextContent('#2RefereeYOU1000 Dice');
  });

  it('shows an honest empty standings state', async () => {
    ready({ leaderboard: [] });
    renderPage();

    expect(await screen.findByText('No tournament balances yet.')).toBeInTheDocument();
  });

  it('keeps markets usable when standings are unavailable', async () => {
    ready();
    mocks.getVirtualLeaderboard.mockRejectedValue(new Error('Standings are offline'));
    renderPage();

    expect(await screen.findByText('Standings are temporarily unavailable.')).toBeInTheDocument();
    expect(screen.getByText('1000')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: /Alice \+ Bea/ })).toBeEnabled();
    expect(screen.queryByText('Virtual Dice is unavailable.')).not.toBeInTheDocument();
  });

  it('opens only a version-zero game whose full roster is enrolled', async () => {
    const outsider = { ...game, id: 'game-2', teams: { ...game.teams, clay: ['cam', 'outsider'] } };
    ready({ markets: [], liveGames: [game, outsider] });
    renderPage();

    const open = await screen.findByRole('button', { name: 'Open picks' });
    expect(screen.getAllByRole('button', { name: 'Open picks' })).toHaveLength(1);
    fireEvent.click(open);
    await waitFor(() => expect(mocks.createVirtualMarket).toHaveBeenCalledWith('token', 't1', 'game-1'));
  });

  it('restores a settled pick and corrected bankroll after refresh', async () => {
    ready({
      markets: [{ ...market, status: 'settled', settled_selection: 'blue', settlement_revision: 1 }],
      picks: [{ id: 8, market_id: 4, selection: 'blue', stake: 300, potential_return: 500, status: 'won' }],
      liveGames: [], balance: 1200,
    });
    renderPage();

    expect(await screen.findByText('1200')).toBeInTheDocument();
    expect(screen.getByText('300 on Alice + Bea')).toBeInTheDocument();
    expect(screen.getByText('won')).toBeInTheDocument();
    expect(screen.queryByLabelText('Stake')).not.toBeInTheDocument();
  });

  it('keeps a failed load actionable with retry', async () => {
    ready();
    mocks.openVirtualBankroll.mockRejectedValueOnce(new Error('Wallet is offline'));
    renderPage();

    expect(await screen.findByRole('alert')).toHaveTextContent('Wallet is offline');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    expect(await screen.findByText('1000')).toBeInTheDocument();
  });

  it('reuses the command id when an ambiguous pick is retried', async () => {
    ready();
    mocks.placeVirtualPick.mockRejectedValueOnce(new Error('Network interrupted')).mockResolvedValueOnce({ id: 8 });
    renderPage();

    const team = await screen.findByRole('button', { name: /Alice \+ Bea/ });
    fireEvent.click(team);
    expect(await screen.findByRole('alert')).toHaveTextContent('retry without duplicating');
    fireEvent.click(team);
    await waitFor(() => expect(mocks.placeVirtualPick).toHaveBeenCalledTimes(2));
    const first = mocks.placeVirtualPick.mock.calls[0][3].client_pick_id;
    const second = mocks.placeVirtualPick.mock.calls[1][3].client_pick_id;
    expect(second).toBe(first);
  });
});
