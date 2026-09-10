import React from 'react';
import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import EloDistribution, { summarizeRatings } from './EloDistribution.jsx';

describe('ELO distribution', () => {
  const entries = [
    { user_id: 'low', elo_rating: 1400, is_provisional: false },
    { user_id: 'middle', elo_rating: 1500, is_provisional: false },
    { user_id: 'high', elo_rating: 1600, is_provisional: false },
    { user_id: 'placing', elo_rating: 1700, is_provisional: true },
  ];

  it('summarizes only established ratings in discrete buckets', () => {
    const summary = summarizeRatings(entries);
    expect(summary.count).toBe(3);
    expect(summary.mean).toBe(1500);
    expect(summary.minimum).toBe(1400);
    expect(summary.maximum).toBe(1600);
    expect(summary.buckets.reduce((sum, bucket) => sum + bucket.count, 0)).toBe(3);
  });

  it('renders the population curve', () => {
    render(<EloDistribution entries={entries} currentUserId="middle" />);
    expect(screen.getByRole('img', { name: /ELO distribution from 1400 to 1600/ })).toBeInTheDocument();
    expect(screen.getByText('3 ranked players')).toBeInTheDocument();
  });

  it('does not highlight a provisional current player in the ranked distribution', () => {
    const { container } = render(<EloDistribution entries={entries} currentUserId="placing" />);
    expect(container.querySelector('.jk-elo-distribution-bucket.is-you')).toBeNull();
  });
});
