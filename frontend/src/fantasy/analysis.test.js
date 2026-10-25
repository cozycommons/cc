import { describe, expect, it } from 'vitest';
import { cleanSnapshot } from './source.js';
import { gamesLeft, matchupRead, notableSwings, playerSwings, seasonRead, weekNotes } from './analysis.js';
import { SNAPSHOT_V2 } from './fixture.js';

const team = name => ({ id: name.length, name });
const day = (state, games, actual = null) => ({ date: '2026-10-2' + games[0], state, actual, expected: [1, 1], games });
const matchup = (chance, scores, days, key = 'k') => ({ key, home: team('Home'), away: team('Away'), chance, scores, days });

describe('matchupRead', () => {
  it('names a favorite that trails, with games left', () => {
    const m = matchup(27, [768, 754], [day('projected', [3, 5])]);
    expect(gamesLeft(m)).toEqual([3, 5]);
    expect(matchupRead(m)).toEqual({ side: 1, headline: 'Away 73%', facts: ['Down 14', '5 games left vs 3'] });
  });

  it('handles leads, finished weeks, ties and the last live games', () => {
    expect(matchupRead(matchup(80, [700, 640], [day('projected', [4, 4])])).facts).toEqual(['Up 60', '4 games left each']);
    expect(matchupRead(matchup(100, [700, 640], [day('final', [4, 4], [100, 90])]))).toEqual({ side: 0, headline: 'Home wins', facts: ['Final', '700–640'] });
    expect(matchupRead(matchup(40, [650.4, 650.2], [day('final', [4, 4], [100, 90])])).headline).toBe('Tied 650–650');
    expect(matchupRead(matchup(99, [700, 640], [day('live', [4, 4], [100, 90])])).facts).toEqual(['Up 60', 'Last games in progress']);
  });
});

describe('season and week reads', () => {
  const data = cleanSnapshot(structuredClone(SNAPSHOT_V2));
  it('names the season leader and why', () => {
    const rows = [...data.season.modes.balanced].sort((a, b) => b.title_pct - a.title_pct);
    expect(seasonRead(rows)).toMatchObject({ leader: 'Glass Cleaners' });
  });
  it('tags settled games and the closest race, linking to it', () => {
    const lock = matchup(97, [705, 496], [day('projected', [3, 3])], 'a');
    const close = matchup(48, [600, 610], [day('projected', [4, 5])], 'b');
    expect(weekNotes([lock, close])).toEqual([
      { tone: 'lock', tag: 'Locked', text: 'Home' },
      { tone: 'close', tag: 'Coin flip', key: 'b', text: 'Home vs Away', detail: 'Away 52% · Up 10 · 5 games left vs 4' },
    ]);
  });
});

describe('player swings', () => {
  const played = (players, state = 'final') => ({ date: '2026-10-21', state, actual: [1, 1], expected: [1, 1], games: [1, 1], players });
  const m = matchup(60, [100, 90], [
    played([[{ id: 1, name: 'Tobias Harris', points: 0, expected: 30 }, { id: 2, name: 'Tyler Herro', points: 52, expected: 30 }], []]),
    played([[{ id: 1, name: 'Tobias Harris', points: 4, expected: 30 }], [{ id: 3, name: 'Quiet', points: 25, expected: 24 }]]),
  ]);
  it('totals actual against expected per player across finished days', () => {
    expect(playerSwings(m)[0][0]).toMatchObject({ name: 'Tobias Harris', actual: 4, expected: 60, games: 2, diff: -56 });
  });
  it('names big misses and the biggest carry, and skips small gaps', () => {
    const [home, away] = playerSwings(m).map(rows => notableSwings(rows));
    expect(home.cold.map(r => r.name)).toEqual(['Tobias Harris']);
    expect(home.hot.map(r => r.name)).toEqual(['Tyler Herro']);
    expect(away).toEqual({ cold: [], hot: [] });
  });
  it('tags the coldest and hottest players of the week', () => {
    const notes = weekNotes([m]);
    expect(notes.find(n => n.tone === 'cold')).toMatchObject({ text: 'Tobias Harris', detail: '4 of 60 expected · Home' });
    expect(notes.find(n => n.tone === 'hot')).toMatchObject({ text: 'Tyler Herro', detail: '52 vs 30 expected · Home' });
  });
  it('leaves live games and players without an expectation out', () => {
    const live = matchup(60, [1, 1], [played([[{ id: 1, name: 'Early', points: 0, expected: 40 }], []], 'live')]);
    expect(playerSwings(live)).toEqual([[], []]);
    const bare = matchup(60, [1, 1], [played([[{ id: 1, name: 'X', points: 0 }], []])]);
    expect(playerSwings(bare)).toEqual([[], []]);
  });
});
