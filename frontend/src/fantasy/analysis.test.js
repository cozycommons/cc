import { describe, expect, it } from 'vitest';
import { cleanSnapshot } from './source.js';
import { gamesLeft, matchupReason, playerSwings, seasonStory, swingLines, weekStory } from './analysis.js';
import { SNAPSHOT_V2 } from './fixture.js';

const team = name => ({ id: name.length, name });
const day = (state, games, actual = null) => ({ date: '2026-10-2' + games[0], state, actual, expected: [1, 1], games });
const matchup = (chance, scores, days) => ({ home: team('Home'), away: team('Away'), chance, scores, days });

describe('matchupReason', () => {
  it('explains a favorite that trails on more games left', () => {
    const m = matchup(73, [768, 754], [day('projected', [3, 5])]);
    expect(gamesLeft(m)).toEqual([3, 5]);
    expect(matchupReason({ ...m, chance: 27 })).toBe('Away is 73% despite trailing by 14: 5 games left to 3.');
  });

  it('explains a leader and a finished week', () => {
    expect(matchupReason(matchup(80, [700, 640], [day('projected', [4, 4])]))).toBe('Home is 80%: up 60 with 4 games left each.');
    expect(matchupReason(matchup(100, [700, 640], [day('final', [4, 4], [100, 90])]))).toBe('Home wins 700–640.');
    expect(matchupReason(matchup(40, [650.4, 650.2], [day('final', [4, 4], [100, 90])]))).toBe('Home and Away tie 650–650.');
    expect(matchupReason(matchup(99, [700, 640], [day('live', [4, 4], [100, 90])]))).toBe('Home is 99%: up 60 with the last games still going.');
  });
});

describe('stories', () => {
  const data = cleanSnapshot(structuredClone(SNAPSHOT_V2));
  it('season story names the leader and the reason', () => {
    const rows = [...data.season.modes.balanced].sort((a, b) => b.title_pct - a.title_pct);
    expect(seasonStory(rows)).toMatch(/^Glass Cleaners leads because /);
  });
  it('week story picks out settled games and the closest race', () => {
    const lock = matchup(97, [705, 496], [day('projected', [3, 3])]);
    const close = matchup(48, [600, 610], [day('projected', [4, 5])]);
    expect(weekStory([lock, close])).toBe('Home is all but done. Closest race: Home vs Away. Away is 52%: up 10 with 5 games left to 4.');
  });
});

describe('player swings', () => {
  const played = (players, state = 'final') => ({ date: '2026-10-21', state, actual: [1, 1], expected: [1, 1], games: [1, 1], players });
  const m = matchup(60, [100, 90], [
    played([[{ id: 1, name: 'Tobias Harris', points: 0, expected: 30 }, { id: 2, name: 'Tyler Herro', points: 52, expected: 30 }], []]),
    played([[{ id: 1, name: 'Tobias Harris', points: 4, expected: 30 }], [{ id: 3, name: 'Quiet', points: 25, expected: 24 }]]),
  ]);
  it('totals actual against expected per player across played days', () => {
    expect(playerSwings(m)[0][0]).toMatchObject({ name: 'Tobias Harris', actual: 4, expected: 60, games: 2, diff: -56 });
  });
  it('names big misses and the biggest carry, and stays quiet on small gaps', () => {
    expect(swingLines(m)).toEqual(['Below: Tobias Harris 4 vs 60 expected. Above: Tyler Herro 52 vs 30 expected', '']);
  });
  it('leaves live games out until they finish', () => {
    const live = matchup(60, [1, 1], [played([[{ id: 1, name: 'Early', points: 0, expected: 40 }], []], 'live')]);
    expect(playerSwings(live)).toEqual([[], []]);
  });
  it('ignores players without an expectation', () => {
    const bare = matchup(60, [1, 1], [played([[{ id: 1, name: 'X', points: 0 }], []])]);
    expect(swingLines(bare)).toEqual(['', '']);
  });
});
