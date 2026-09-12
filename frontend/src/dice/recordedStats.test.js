import { describe, expect, it } from 'vitest';
import { aggregateRecordedStats, metricLeader, metricLeaders } from './recordedStats.js';

describe('recorded stats aggregation', () => {
  it('adds only observed player stats and preserves coverage', () => {
    const result = aggregateRecordedStats([{
      players: [{ user_id: 'a', display_name: 'Alice' }],
      recorded_stats: {
        coverage: 'partial', observations: 3,
        players: { a: { outcomes: { point: 1, miss: 2 }, table_catches: 1, fifa_saves: 1 } },
      },
    }, { players: [{ user_id: 'a', display_name: 'Alice' }] }]);

    expect(result).toMatchObject({ recordedGames: 1, completeGames: 0, observations: 3 });
    expect(result.players[0]).toMatchObject({
      display_name: 'Alice', throws: 3, tableHits: 1, tableHitRate: 33,
      points: 1, misses: 2, catches: 1, fifaActions: 1,
    });
  });

  it('does not crown a rate leader below the sample floor', () => {
    expect(metricLeader([{ user_id: 'a', throws: 4, tableHitRate: 100 }], 'tableHitRate', { minimumThrows: 5 })).toBeNull();
  });

  it('returns every player tied for a metric lead', () => {
    const players = [
      { user_id: 'a', display_name: 'Alpha', throws: 8, scores: 3 },
      { user_id: 'b', display_name: 'Bravo', throws: 5, scores: 3 },
      { user_id: 'c', display_name: 'Charlie', throws: 9, scores: 2 },
    ];

    expect(metricLeaders(players, 'scores').map((player) => player.user_id)).toEqual(['a', 'b']);
  });
});
