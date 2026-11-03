import { describe, expect, it } from 'vitest';
import { diceParentPath, isDiceHome } from './diceBack.js';

describe('diceParentPath', () => {
  it.each([
    ['/dice/game/g1', '', '/dice'],
    ['/dice/game/g1/edit', '', '/dice/game/g1'],
    ['/dice/tournament/t1/virtual', '', '/dice/tournament/t1'],
    ['/dice/tournament/t1', '', '/dice/tournaments'],
    ['/dice/live/m1', '', '/dice/live'],
    ['/dice/stats/duos/a-b', '', '/dice/stats?view=duos'],
    ['/dice/stats/streaks/u1', '', '/dice/stats?view=streaks'],
    ['/dice/leaderboard/sinks', '', '/dice/stats'],
    ['/dice/elo-explained', '', '/dice/leaderboard/elo'],
    ['/dice/stats', '?view=streaks', '/dice/stats'],
    ['/dice/stats', '', '/dice'],
    ['/dice/profile/u1', '', '/dice'],
  ])('%s%s → %s', (pathname, search, parent) => {
    expect(diceParentPath(pathname, search)).toBe(parent);
  });

  it('recognises the home page', () => {
    expect(isDiceHome('/dice')).toBe(true);
    expect(isDiceHome('/dice/')).toBe(true);
    expect(isDiceHome('/dice/stats')).toBe(false);
  });
});
