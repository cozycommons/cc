import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  getGame: vi.fn(),
  searchProfiles: vi.fn(),
  updateGame: vi.fn(),
}));

vi.mock('../api.js', () => ({ diceApi: mocks }));
vi.mock('../components/PlayerPicker.jsx', () => ({
  default: ({ label, value }) => <div>{label}: {value?.display_name}</div>,
}));
vi.mock('../components/SinkCountInput.jsx', () => ({
  default: ({ name, statLabel, value }) => <div>{name} {statLabel}: {value}</div>,
}));
vi.mock('@/components/ui/button', () => ({
  Button: ({ children, variant: _variant, ...props }) => <button {...props}>{children}</button>,
}));
vi.mock('@/components/ui/input', () => ({
  Input: (props) => <input {...props} />,
}));

import LogMatch from './LogMatch.jsx';

const players = [
  { user_id: 'u1', display_name: 'Alpha', team: 1, self_sinks: 0, sinks: 0 },
  { user_id: 'u2', display_name: 'Bravo', team: 1, self_sinks: 0, sinks: 0 },
  { user_id: 'u3', display_name: 'Charlie', team: 2, self_sinks: 0, sinks: 0 },
  { user_id: 'u4', display_name: 'Delta', team: 2, self_sinks: 0, sinks: 0 },
];

const game = {
  id: 'game-1',
  ranked: true,
  team1_score: 5,
  team2_score: 4,
  tournament_id: null,
  updated_at: '2026-09-05T01:00:00Z',
  players,
};

function renderEditor() {
  return render(
    <MemoryRouter initialEntries={['/dice/game/game-1/edit']}>
      <Routes>
        <Route
          path="/dice/game/:gameId/edit"
          element={<LogMatch editMode auth={{ user: { id: 'u1' }, token: 'token', isAdmin: false, loading: false }} />}
        />
        <Route path="/dice/game/:gameId" element={<p>Saved game</p>} />
      </Routes>
    </MemoryRouter>,
  );
}

function renderLogger() {
  return render(
    <MemoryRouter>
      <LogMatch auth={{ user: { id: 'u1' }, token: 'token', isAdmin: false, loading: false }} />
    </MemoryRouter>,
  );
}

describe('LogMatch editing', () => {
  afterEach(() => vi.resetAllMocks());

  it('retains a stale edit and requires an explicit overwrite against the latest revision', async () => {
    const latest = {
      ...game,
      team1_score: 6,
      team2_score: 4,
      tournament_id: 'tournament-2',
      updated_at: '2026-09-05T01:01:00Z',
      players: players.map((player) => (
        player.user_id === 'u2'
          ? { ...player, team: 2, self_sinks: 3, counts_for_group_stage: false }
          : player.user_id === 'u3'
            ? { ...player, team: 1, sinks: 2 }
            : player
      )),
    };
    mocks.searchProfiles.mockResolvedValue(players);
    mocks.getGame.mockResolvedValueOnce(game).mockResolvedValueOnce(latest);
    mocks.updateGame
      .mockRejectedValueOnce({ status: 409, detail: { code: 'dice_game.stale_update' } })
      .mockResolvedValueOnce({ id: 'game-1' });

    renderEditor();
    const scores = await screen.findAllByRole('spinbutton');
    fireEvent.change(scores[0], { target: { value: '7' } });
    fireEvent.click(screen.getByRole('radio', { name: 'Unranked — Casual game' }));
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));

    const recovery = await screen.findByRole('region', { name: 'Unsaved match changes' });
    expect(recovery).toHaveTextContent(/Latest:.*Team 1: Alpha.*Charlie \(2 sinks, 0 self-sinks\)/);
    expect(recovery).toHaveTextContent(/Team 2: Bravo \(0 sinks, 3 self-sinks, substitute\).*Delta/);
    expect(recovery).toHaveTextContent(/Latest:.*Score: 6–4\. Ranked/);
    expect(recovery).toHaveTextContent(/Tournament: tournament-2/);
    expect(recovery).toHaveTextContent(/Yours:.*Team 1: Alpha.*Bravo \(0 sinks, 0 self-sinks\)/);
    expect(recovery).toHaveTextContent(/Team 2: Charlie \(0 sinks, 0 self-sinks\).*Delta/);
    expect(recovery).toHaveTextContent(/Yours:.*Score: 7–4\. Normal/);
    expect(recovery).toHaveTextContent(/Tournament: none/);
    expect(scores[0]).toHaveValue(7);
    expect(screen.getByRole('radio', { name: 'Ranked — Affects ELO' })).not.toBeChecked();
    expect(mocks.updateGame.mock.calls[0][2]).toMatchObject({
      expected_updated_at: game.updated_at,
      team1_score: 7,
      ranked: false,
    });

    fireEvent.click(screen.getByRole('button', { name: 'Save my changes now' }));
    await screen.findByText('Saved game');
    expect(mocks.updateGame.mock.calls[1][2]).toMatchObject({
      expected_updated_at: latest.updated_at,
      team1_score: 7,
      ranked: false,
    });
  });

  it('can discard a stale edit and hydrate the canonical result', async () => {
    const latest = {
      ...game,
      team1_score: 8,
      team2_score: 2,
      ranked: false,
      updated_at: '2026-09-05T01:02:00Z',
    };
    mocks.searchProfiles.mockResolvedValue(players);
    mocks.getGame.mockResolvedValueOnce(game).mockResolvedValueOnce(latest);
    mocks.updateGame.mockRejectedValueOnce({
      status: 409,
      detail: { code: 'dice_game.stale_update' },
    });

    renderEditor();
    const scores = await screen.findAllByRole('spinbutton');
    fireEvent.change(scores[0], { target: { value: '7' } });
    fireEvent.click(screen.getByRole('button', { name: 'Save Changes' }));
    fireEvent.click(await screen.findByRole('button', { name: 'Discard my changes and reload' }));

    await waitFor(() => expect(scores[0]).toHaveValue(8));
    expect(scores[1]).toHaveValue(2);
    expect(screen.getByRole('radio', { name: 'Ranked — Affects ELO' })).not.toBeChecked();
  });
});

describe('LogMatch creation', () => {
  afterEach(() => vi.resetAllMocks());

  it('starts new manually logged games as ranked', async () => {
    mocks.searchProfiles.mockResolvedValue([]);
    renderLogger();

    await waitFor(() => expect(mocks.searchProfiles).toHaveBeenCalled());
    expect(screen.getByRole('radio', { name: 'Ranked — Affects ELO' })).toBeChecked();
    expect(screen.getByRole('radio', { name: 'Unranked — Casual game' })).not.toBeChecked();
  });
});
