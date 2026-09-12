import React from 'react';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it } from 'vitest';
import LeaderboardRow from './LeaderboardRow.jsx';

const profile = { user_id: 'u1', display_name: 'Alpha', avatar_url: null };

describe('LeaderboardRow', () => {
  it('announces ties while displaying the plain competition rank', () => {
    render(
      <MemoryRouter>
        <LeaderboardRow rank={2} tied profile={profile} value={1500} valueLabel="ELO" />
      </MemoryRouter>,
    );

    expect(screen.getByLabelText('Tied rank 2')).toHaveTextContent('2');
    expect(screen.getByLabelText('Tied rank 2')).not.toHaveTextContent('T-');
  });

  it('announces provisional players as unranked', () => {
    render(
      <MemoryRouter>
        <LeaderboardRow rank={null} unranked profile={profile} value={1500} valueLabel="ELO" />
      </MemoryRouter>,
    );

    expect(screen.getByLabelText('Unranked')).toHaveTextContent('—');
  });

  it('keeps count comparison bars for sink leaderboards', () => {
    render(
      <MemoryRouter>
        <LeaderboardRow rank={2} profile={profile} value={4} valueLabel="sinks" barMode="count" maxValue={8} barTone="clay" />
      </MemoryRouter>,
    );

    const bar = screen.getByLabelText('4 out of 8');
    expect(bar.querySelector('.jk-leaderboard-bar')).toHaveStyle({ width: '50%' });
    expect(bar.querySelector('.jk-leaderboard-bar')).toHaveClass('is-clay');
  });

  it('renders centered continuous bars for the full ELO leaderboard', () => {
    render(
      <MemoryRouter>
        <LeaderboardRow rank={1} profile={profile} value={1600} valueLabel="ELO" barMode="elo" maxValue={200} />
      </MemoryRouter>,
    );

    const bar = screen.getByLabelText('100 points above 1500');
    expect(bar.querySelector('.jk-leaderboard-bar')).toHaveStyle({ width: '25%' });
    expect(bar.querySelector('.jk-leaderboard-bar')).toHaveClass('is-positive');
  });
});
