import React from 'react';
import { render, screen, within } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ getDuoDetail: vi.fn() }));
vi.mock('../api.js', () => ({ diceApi: mocks }));
vi.mock('../../analytics/usePageviewTracking', () => ({ usePageviewTracking: vi.fn() }));
vi.mock('../components/PlayerAvatar.jsx', () => ({ default: ({ profile }) => <span>{profile.display_name} avatar</span> }));

import DuoDetail from './DuoDetail.jsx';

describe('DuoDetail', () => {
  afterEach(() => vi.clearAllMocks());

  it('renders rating history, head-to-head records, and source game links', async () => {
    mocks.getDuoDetail.mockResolvedValue({
      summary: {
        duo_id: '3:u13:u2',
        members: [{ user_id: 'u1', display_name: 'Alpha' }, { user_id: 'u2', display_name: 'Bravo' }],
        elo: 1600,
        rating_deviation: 120,
        conservative_score: 1480,
        wins: 3,
        losses: 1,
        games: 4,
        win_rate: 0.75,
        rank: 1,
        current_streak: 2,
        best_streak: 3,
      },
      rating_history: [{ game_id: 'game-1', opponent_duo_id: 'other', before_elo: 1500, after_elo: 1525, delta: 25, result: 'win', score: [11, 8], played_at: '2026-01-01T00:00:00Z' }],
      games: [{ game_id: 'game-1', opponent_duo_id: 'other', before_elo: 1500, after_elo: 1525, delta: 25, result: 'win', score: [11, 8], played_at: '2026-01-01T00:00:00Z' }],
      head_to_head: [{ opponent_duo_id: 'other', wins: 1, losses: 0, games: 1, latest_meeting: '2026-01-01T00:00:00Z', game_ids: ['game-1'] }],
    });

    render(<MemoryRouter initialEntries={['/dice/stats/duos/3%3Au1%3Au2']}><Routes><Route path="/dice/stats/duos/:duoId" element={<DuoDetail auth={{ token: 'token' }} />} /></Routes></MemoryRouter>);

    expect(await screen.findByText('Alpha + Bravo')).toBeInTheDocument();
    expect(screen.getByText('Rank #1 · 4 games')).toBeInTheDocument();
    expect(screen.getByText('// RATING HISTORY')).toBeInTheDocument();
    expect(screen.getByRole('link', { name: /game-1/ })).toHaveAttribute('href', '/dice/game/game-1?duo=1');
    expect(screen.getByText('// HEAD TO HEAD')).toBeInTheDocument();
    expect(mocks.getDuoDetail).toHaveBeenCalledWith('token', '3:u1:u2');
  });
});

function synergyDetail(difference, { apart = [], bigMoments = null } = {}) {
  return {
    summary: {
      duo_id: 'pair', members: [{ user_id: 'u1', display_name: 'Alpha' }, { user_id: 'u2', display_name: 'Bravo' }],
      elo: 1500, wins: 3, losses: 9, games: 12, win_rate: 0.25, rank: 1, current_streak: 0, best_streak: 1,
      synergy: { wins: 3, losses: 9, games: 12, expected_wins: 6.1, wins_above_expected: difference, apart },
    },
    rating_history: [], games: [], head_to_head: [], big_moments: bigMoments,
  };
}

function renderSynergy(detail) {
  mocks.getDuoDetail.mockResolvedValue(detail);
  render(<MemoryRouter initialEntries={['/dice/stats/duos/pair']}><Routes><Route path="/dice/stats/duos/:duoId" element={<DuoDetail auth={{ token: 'token' }} />} /></Routes></MemoryRouter>);
}

it.each([[2.44, 'Better together', '2.4 wins over expected'], [-3.14, 'Better apart', '3.1 wins under expected']])('shows pair comparison for %s', async (difference, title, description) => {
  renderSynergy(synergyDetail(difference, { apart: [{ user_id: 'u1', wins: 8, losses: 2, games: 10 }, { user_id: 'u2', wins: 7, losses: 1, games: 8 }] }));
  expect(await screen.findByRole('heading', { name: title })).toBeInTheDocument();
  expect(screen.getByText(description)).toBeInTheDocument();
  expect(screen.getByText('Apart: Alpha 8–2 · Bravo 7–1')).toBeInTheDocument();
  expect(within(screen.getByLabelText('Duo synergy')).queryByText(/together ·/)).not.toBeInTheDocument();
  expect(screen.queryByText(/0–0/)).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Big moments')).not.toBeInTheDocument();
});

it('omits an unavailable comparison and live split', async () => {
  const detail = synergyDetail(0);
  detail.summary.synergy = null;
  renderSynergy(detail);
  await screen.findByText('Alpha + Bravo');
  expect(screen.queryByLabelText('Duo synergy')).not.toBeInTheDocument();
  expect(screen.queryByLabelText('Big moments')).not.toBeInTheDocument();
});

it('shows both names and percentages without ranking the big moments split', async () => {
  renderSynergy(synergyDetail(2.4, { bigMoments: { games: 10, members: [{ user_id: 'u1', share: 0.625 }, { user_id: 'u2', share: 0.375 }] } }));
  expect(await screen.findByRole('heading', { name: 'Big moments' })).toBeInTheDocument();
  expect(screen.getByText('Alpha · 63%')).toBeInTheDocument();
  expect(screen.getByText('Bravo · 37%')).toBeInTheDocument();
  expect(screen.getByText('Share of big swings')).toBeInTheDocument();
  const tones = screen.getByLabelText('Big moments').querySelector('[aria-hidden="true"]').children;
  expect(tones[0].style.background).toBe('var(--team1-color)');
  expect(tones[1].style.background).toBe('var(--team2-color)');
});


it.each([-0.049, 0, 0.049])('shows a neutral label without a hero number for %s', async (difference) => {
  renderSynergy(synergyDetail(difference));
  expect(await screen.findByRole('heading', { name: 'Right on expected' })).toBeInTheDocument();
  const card = screen.getByLabelText('Duo synergy');
  expect(within(card).queryByText(/wins? (over|under) expected/)).not.toBeInTheDocument();
  expect(card.querySelector('.jk-display')).toBeNull();
});

it('uses short names in one apart line when full names are long', async () => {
  const detail = synergyDetail(1, { apart: [{ user_id: 'u1', wins: 8, losses: 2 }, { user_id: 'u2', wins: 3, losses: 9 }] });
  detail.summary.members[0].display_name = 'Golf Guard';
  detail.summary.members[1].display_name = 'India In';
  renderSynergy(detail);
  expect(await screen.findByText('1.0 win over expected')).toBeInTheDocument();
  expect(screen.getByText('Apart: Golf 8–2 · India 3–9')).toBeInTheDocument();
});
