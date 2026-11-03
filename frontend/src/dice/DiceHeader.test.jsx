import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('./components/PlayerAvatar.jsx', () => ({ default: () => <span>Avatar</span> }));

import DiceHeader from './DiceHeader.jsx';

function Location() {
  return <output>{useLocation().pathname}</output>;
}

function renderHeader(effective = true) {
  const auth = {
    user: { id: 'user-1' },
    profile: {},
    loading: false,
    signIn: vi.fn(),
    features: { dice_live_referee: { effective } },
  };
  render(
    <MemoryRouter initialEntries={['/dice']}>
      <DiceHeader auth={auth} />
      <Location />
    </MemoryRouter>,
  );
}

describe('DiceHeader match action', () => {
  it('uses ELO as the single player directory', () => {
    renderHeader(true);

    fireEvent.click(screen.getByRole('button', { name: 'Players' }));

    expect(screen.getByText('/dice/leaderboard/elo')).toBeInTheDocument();
  });

  it('provides profiles a direct path to Stats', () => {
    renderHeader(true);

    fireEvent.click(screen.getByRole('button', { name: 'Stats' }));

    expect(screen.getByText('/dice/stats')).toBeInTheDocument();
  });

  it('ignores a stale opt-out when exposing Stats', () => {
    renderHeader(false);

    fireEvent.click(screen.getByRole('button', { name: 'Stats' }));
    expect(screen.getByText('/dice/stats')).toBeInTheDocument();
  });

  it('starts the live match flow', () => {
    renderHeader(true);

    fireEvent.click(screen.getByRole('button', { name: 'Start Match' }));

    expect(screen.getByText('/dice/live')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Log Match' })).not.toBeInTheDocument();
  });

  it('does not restore direct logging for a stale opt-out', () => {
    renderHeader(false);

    fireEvent.click(screen.getByRole('button', { name: 'Start Match' }));

    expect(screen.getByText('/dice/live')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Log Match' })).not.toBeInTheDocument();
  });
});

describe('DiceHeader back button', () => {
  function renderAt(entries, index = entries.length - 1) {
    const auth = { user: null, profile: null, loading: false, signIn: vi.fn() };
    render(
      <MemoryRouter initialEntries={entries} initialIndex={index}>
        <DiceHeader auth={auth} />
        <LocationWithSearch />
      </MemoryRouter>,
    );
  }

  function LocationWithSearch() {
    const location = useLocation();
    return <output>{`${location.pathname}${location.search}`}</output>;
  }

  it('is hidden on the Dice home page', () => {
    renderAt(['/dice']);
    expect(screen.queryByRole('button', { name: 'Back' })).not.toBeInTheDocument();
  });

  it('steps back through in-app history, including Stats views', () => {
    renderAt(['/dice', '/dice/stats', '/dice/stats?view=duos', '/dice/stats/duos/a-b']);

    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByText('/dice/stats?view=duos')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByText('/dice/stats')).toBeInTheDocument();
  });

  it('goes to the parent page when opened directly from a link', () => {
    renderAt(['/dice/game/g1/edit']);

    fireEvent.click(screen.getByRole('button', { name: 'Back' }));
    expect(screen.getByText('/dice/game/g1')).toBeInTheDocument();
  });
});
