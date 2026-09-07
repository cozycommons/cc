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
});
