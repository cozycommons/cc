import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ auth: null }));

vi.mock('./useDiceAuth.js', () => ({ useDiceAuth: () => mocks.auth }));
vi.mock('./DiceHeader.jsx', () => ({ default: () => null }));
vi.mock('./pages/Home.jsx', () => ({ default: () => <p>Dice home</p> }));
vi.mock('./pages/LiveLobby.jsx', () => ({ default: ({ auth }) => <p>Live lobby for {auth.profile.user_id}</p> }));
vi.mock('./pages/LiveGame.jsx', () => ({ default: () => <p>Live game</p> }));
vi.mock('./pages/VirtualDice.jsx', () => ({ default: () => <p>Virtual Dice</p> }));
vi.mock('./pages/EloLeaderboard.jsx', () => ({ default: () => <p>ELO players</p> }));
vi.mock('./pages/Tournaments.jsx', () => ({ default: () => <p>Tournament directory</p> }));

import DiceApp from './App.jsx';

const renderDice = (path = '/dice/live') => render(
  <MemoryRouter initialEntries={[path]}>
    <Routes><Route path="/dice/*" element={<DiceApp />} /></Routes>
  </MemoryRouter>,
);

describe('Dice private route auth hydration', () => {
  it('waits for profile registration before mounting a direct live route', async () => {
    mocks.auth = {
      user: { id: 'u1' }, token: 'token', profile: null, loading: true,
      signIn: vi.fn(), signOut: vi.fn(),
    };
    const view = renderDice();
    expect(screen.queryByText(/Live lobby/)).not.toBeInTheDocument();

    mocks.auth = { ...mocks.auth, profile: { user_id: 'u1' }, loading: false };
    view.rerender(<MemoryRouter initialEntries={['/dice/live']}><Routes><Route path="/dice/*" element={<DiceApp />} /></Routes></MemoryRouter>);
    expect(await screen.findByText('Live lobby for u1')).toBeInTheDocument();
  });

  it('remounts route state when the signed-in identity changes', async () => {
    mocks.auth = {
      user: { id: 'u1' }, token: 'token-1', profile: { user_id: 'u1' }, loading: false,
      signIn: vi.fn(), signOut: vi.fn(),
    };
    const view = renderDice();
    expect(await screen.findByText('Live lobby for u1')).toBeInTheDocument();

    mocks.auth = {
      ...mocks.auth, user: { id: 'u2' }, token: 'token-2', profile: { user_id: 'u2' },
    };
    view.rerender(<MemoryRouter initialEntries={['/dice/live']}><Routes><Route path="/dice/*" element={<DiceApp />} /></Routes></MemoryRouter>);
    expect(await screen.findByText('Live lobby for u2')).toBeInTheDocument();
  });

  it.each(['/dice/live', '/dice/live/match-1'])('redirects an anonymous direct visit to %s', async (path) => {
    mocks.auth = {
      user: null, token: null, profile: null, loading: false,
      signIn: vi.fn(), signOut: vi.fn(),
    };
    renderDice(path);
    expect(await screen.findByText('Dice home')).toBeInTheDocument();
    expect(screen.queryByText('Live game')).not.toBeInTheDocument();
  });

  it('keeps the old players URL as a redirect to ELO player discovery', async () => {
    mocks.auth = {
      user: null, token: null, profile: null, loading: false,
      signIn: vi.fn(), signOut: vi.fn(),
    };
    renderDice('/dice/players');

    expect(await screen.findByText('ELO players')).toBeInTheDocument();
  });

  it('serves the tournament directory directly', async () => {
    mocks.auth = {
      user: null, token: null, profile: null, loading: false,
      signIn: vi.fn(), signOut: vi.fn(),
    };
    renderDice('/dice/tournaments');

    expect(await screen.findByText('Tournament directory')).toBeInTheDocument();
  });
});
