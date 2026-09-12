import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

vi.mock('./PlayerAvatar.jsx', () => ({ default: ({ profile }) => <span>{profile.display_name} avatar</span> }));

import PlayerGameStats, { playerGameMetrics } from './PlayerGameStats.jsx';

const teams = [
  { id: 'blue', label: 'Alpha + Bravo', players: [{ user_id: 'a', display_name: 'Alpha' }, { user_id: 'b', display_name: 'Bravo' }] },
  { id: 'clay', label: 'Charlie + Delta', players: [{ user_id: 'c', display_name: 'Charlie' }, { user_id: 'd', display_name: 'Delta' }] },
];

describe('PlayerGameStats', () => {
  it('derives rates only from canonically projected observed throws', () => {
    expect(playerGameMetrics({ outcomes: { miss: 2, caught: 1, point: 1, sink: 1, invalid: 1 } })).toEqual({
      throws: 6,
      tableHits: 3,
      tableHitRate: 50,
      scoringThrows: 2,
    });
  });

  it('shows individual throwing, catching, and FIFA roles without zero-value clutter', () => {
    render(<PlayerGameStats teams={teams} coverage="partial" live statsByPlayer={{
      a: { outcomes: { point: 1, caught: 1, miss: 2 }, fifa_goals: 1 },
      b: { outcomes: {}, table_catches: 2, fifa_saves: 1 },
      c: { outcomes: { fifa: 1 } },
      d: { outcomes: {} },
    }} />);

    expect(screen.getByText('LIVE PLAYER STATS')).toBeInTheDocument();
    expect(screen.getByText('4 throws · 50% table rate')).toBeInTheDocument();
    expect(screen.getByLabelText('2 catches')).toBeInTheDocument();
    expect(screen.getByLabelText('1 FIFA save')).toBeInTheDocument();
    expect(screen.getAllByText('No recorded throws')).toHaveLength(2);
    expect(screen.getByText('Missing plays are excluded, not counted as misses.')).toBeInTheDocument();
    expect(screen.queryByText('0 sinks')).not.toBeInTheDocument();
  });
});
