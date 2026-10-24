import { describe, expect, it } from 'vitest';
import { favorite, orderMatchups, scorePath } from './paths.js';

const matchup = {
  home: { name: 'Home Team' }, away: { name: 'Away Team' },
  scores: [150, 120], projected_totals: [420, 400], chance: 62,
  days: [
    { date: '2026-10-20', state: 'final', actual: [100, 80], expected: [90, 85], games: [5, 4] },
    { date: '2026-10-21', state: 'live', actual: [50, 40], expected: [120, 110], games: [6, 6] },
    { date: '2026-10-22', state: 'projected', actual: null, expected: [100, 120], games: [5, 6] },
    { date: '2026-10-23', state: 'projected', actual: null, expected: [80, 90], games: [4, 4] },
  ],
};

describe('scorePath', () => {
  it('keeps observed and projected paths separate and ends on the projected totals', () => {
    const rows = scorePath(matchup);
    expect(rows.map(r => r.actual)).toEqual([[100, 80], [150, 120], null, null]);
    expect(rows[1].projected).toEqual([240, 190]);
    expect(rows.at(-1).projected).toEqual([420, 400]);
    expect(rows[0].projected).toBeNull();
  });

  it('never treats a missing final actual as zero, but still shows the projection', () => {
    const rows = scorePath({ ...matchup, days: [{ ...matchup.days[0], actual: [100, null] }, ...matchup.days.slice(1)] });
    expect(rows.every(r => r.actual === null)).toBe(true);
    expect(rows.at(-1).projected).toEqual([420, 400]);
  });
});

describe('pre-tip live day', () => {
  it('projects a live day with no points yet instead of dropping the projection', () => {
    const days = [matchup.days[0], { ...matchup.days[1], actual: null }, ...matchup.days.slice(2)];
    const rows = scorePath({ ...matchup, days });
    expect(rows.map(r => r.actual)).toEqual([[100, 80], null, null, null]);
    expect(rows[0].projected).toEqual([120, 80]);
    expect(rows.at(-1).projected).toEqual([420, 400]);
  });
});

describe('partial live day', () => {
  it('counts points so far, treating a side with no points yet as zero', () => {
    const days = [matchup.days[0], { ...matchup.days[1], actual: [10, null] }, ...matchup.days.slice(2)];
    expect(scorePath({ ...matchup, days })[1].actual).toEqual([110, 80]);
  });
});

describe('ordering', () => {
  it('puts the closest races first and unavailable matchups last', () => {
    const list = [{ chance: 90 }, { unavailable: true }, { chance: 48 }, { chance: 70 }];
    expect(orderMatchups(list).map(m => m.chance ?? 'x')).toEqual([48, 70, 90, 'x']);
    expect(favorite({ chance: 30 })).toBe(1);
    expect(favorite({ chance: 50 })).toBeNull();
  });
});
