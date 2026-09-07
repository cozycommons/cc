import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';

vi.mock('./PlayerAvatar.jsx', () => ({ default: ({ profile }) => <span>{profile.display_name} avatar</span> }));

import SinkLeadersChart from './SinkLeadersChart.jsx';

const sinks = [
  { user_id: 'a', display_name: 'Alpha', sinks: 10 },
  { user_id: 'b', display_name: 'Bravo', sinks: 8 },
  { user_id: 'c', display_name: 'Charlie', sinks: 6 },
  { user_id: 'd', display_name: 'Delta', sinks: 4 },
  { user_id: 'e', display_name: 'Echo', sinks: 2 },
  { user_id: 'me', display_name: 'Local Referee', sinks: 0 },
];

const selfSinks = sinks.map((profile, index) => ({ ...profile, self_sinks: Math.max(0, 5 - index) }));

function renderChart() {
  return render(<MemoryRouter><SinkLeadersChart sinks={sinks} selfSinks={selfSinks} currentUserId="me" /></MemoryRouter>);
}

describe('SinkLeadersChart', () => {
  it('shows five leaders plus a compact current-player column', () => {
    const { container } = renderChart();
    expect(screen.getAllByRole('link', { name: /Rank/ })).toHaveLength(6);
    expect(screen.getByRole('link', { name: /Local Referee, 0 Sinks, you/ })).toBeInTheDocument();
    expect(screen.getByText('#6 · You')).toBeInTheDocument();
    expect(container.querySelector('.jk-vertical-leader.is-current-user .jk-vertical-bar')).toHaveStyle({ height: '0%' });
  });

  it('switches metric, color, and full-board destination without adding labels', () => {
    const { container } = renderChart();
    fireEvent.click(screen.getByRole('button', { name: 'Self-sinks' }));
    expect(screen.getByRole('button', { name: 'Self-sinks' })).toHaveAttribute('aria-pressed', 'true');
    expect(screen.getByRole('link', { name: 'Full board →' })).toHaveAttribute('href', '/dice/leaderboard/self-sinks');
    expect(container.querySelector('.jk-vertical-bar')).toHaveClass('is-clay');
  });
});
