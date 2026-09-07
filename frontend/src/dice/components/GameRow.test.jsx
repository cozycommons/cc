import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('./PlayerAvatar.jsx', () => ({ default: () => <span>avatar</span> }));

import GameRow from './GameRow.jsx';

const game = {
  id: 'g1', ranked: true, winner_team: 1, team1_score: 11, team2_score: 8,
  played_at: '2026-08-29T12:00:00Z',
  players: [
    { user_id: 'u1', display_name: 'Winner', team: 1, elo_before: 1500, elo_after: 1518 },
    { user_id: 'u2', display_name: 'Loser', team: 2, elo_before: 1500, elo_after: 1482 },
  ],
};

describe('GameRow rating movement', () => {
  it('shows the audited gained rating from the viewer snapshot', () => {
    render(<MemoryRouter><GameRow game={game} perspectiveUserId="u1" /></MemoryRouter>);
    expect(screen.getByLabelText('Rating gained 18 points')).toHaveTextContent('+18 ELO');
  });

  it('shows losses truthfully', () => {
    render(<MemoryRouter><GameRow game={game} perspectiveUserId="u2" /></MemoryRouter>);
    expect(screen.getByLabelText('Rating lost 18 points')).toHaveTextContent('-18 ELO');
  });

  it('uses an authoritative override and labels zero as unchanged', () => {
    render(<MemoryRouter><GameRow game={game} perspectiveUserId="u1" ratingDelta={0} /></MemoryRouter>);
    expect(screen.getByLabelText('Rating unchanged by 0 points')).toHaveTextContent('0 ELO');
  });
});
