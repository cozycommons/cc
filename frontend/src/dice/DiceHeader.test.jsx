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
