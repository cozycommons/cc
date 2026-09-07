import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, useLocation } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('./components/PlayerAvatar.jsx', () => ({ default: () => <span>Avatar</span> }));

import DiceHeader from './DiceHeader.jsx';

function Location() {
  return <output>{useLocation().pathname}</output>;
}

function renderHeader(effective) {
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
  it('provides enabled profiles a direct path to the experimental stats page', () => {
    renderHeader(true);

    fireEvent.click(screen.getByRole('button', { name: 'Stats' }));

    expect(screen.getByText('/dice/stats')).toBeInTheDocument();
  });

  it('does not expose the experimental stats page to disabled profiles', () => {
    renderHeader(false);

    expect(screen.queryByRole('button', { name: 'Stats' })).not.toBeInTheDocument();
  });

  it('starts the live match flow when the profile has access', () => {
    renderHeader(true);

    fireEvent.click(screen.getByRole('button', { name: 'Start Match' }));

    expect(screen.getByText('/dice/live')).toBeInTheDocument();
    expect(screen.queryByRole('button', { name: 'Log Match' })).not.toBeInTheDocument();
  });

  it('keeps direct match logging for profiles without access', () => {
    renderHeader(false);

    fireEvent.click(screen.getByRole('button', { name: 'Log Match' }));

    expect(screen.getByText('/dice/log')).toBeInTheDocument();
  });
});
