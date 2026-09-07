import { describe, expect, it } from 'vitest';
import { leaderboardPreview, rankLeaderboard } from './leaderboard.js';

describe('leaderboard helpers', () => {
  it('uses competition ranks for ties', () => {
    const ranked = rankLeaderboard([
      { user_id: 'a', sinks: 8 },
      { user_id: 'b', sinks: 8 },
      { user_id: 'c', sinks: 5 },
    ], 'sinks');

    expect(ranked.map((entry) => entry.rank)).toEqual([1, 1, 3]);
  });

  it('pins the current player only when they are outside the preview', () => {
    const entries = ['a', 'b', 'c', 'me'].map((user_id, index) => ({ user_id, rank: index + 1 }));
    expect(leaderboardPreview(entries, 'me')).toEqual({ leaders: entries.slice(0, 3), current: entries[3] });
    expect(leaderboardPreview(entries, 'b').current).toBeNull();
  });

  it('leaves provisional ELO players unranked', () => {
    const ranked = rankLeaderboard([
      { user_id: 'a', elo_rating: 1550, is_provisional: false },
      { user_id: 'me', elo_rating: 1540, is_provisional: true },
    ], 'elo_rating', { provisionalKey: 'is_provisional' });

    expect(ranked.map((entry) => entry.rank)).toEqual([1, null]);
  });
});
