import { describe, expect, it } from 'vitest';
import { isOnExpected, synergyDescription, synergyGap, synergyRates, synergyTitle, wholePercent } from './duoSynergy.js';

const synergy = (wins, games, expectedWins) => ({ wins, losses: games - wins, games, expected_wins: expectedWins });

describe('duo comparison wording', () => {
  it('compares the together win rate with the expected rate', () => {
    const record = synergy(20, 21, 10.5);
    expect(synergyRates(record)).toEqual({ together: 95, expected: 50 });
    expect(synergyDescription(record)).toBe('95% wins, 50% expected');
    expect(synergyTitle(record)).toBe('Better together');
    expect(synergyTitle(synergy(1, 21, 10.5))).toBe('Better apart');
  });

  it('is independent of game volume', () => {
    expect(synergyGap(synergy(5, 5, 2.5))).toBe(50);
    expect(synergyGap(synergy(20, 21, 10.5))).toBe(45);
  });

  it.each([[101, 200, 101], [100, 200, 100.9]])('is neutral when both rates display the same (%s of %s)', (wins, games, expectedWins) => {
    const record = synergy(wins, games, expectedWins);
    expect(isOnExpected(record)).toBe(true);
    expect(synergyTitle(record)).toBe('Right on expected');
  });

  it('labels a one-point displayed gap', () => {
    const record = synergy(101, 200, 100.9);
    expect(synergyDescription(record)).toBe('51% wins, 50% expected');
    expect(synergyTitle(record)).toBe('Better together');
  });

  it('rounds half up like the backend', () => {
    expect([0.125, 0.5, 0.004, 0.994, 20 / 21].map(wholePercent)).toEqual([13, 50, 0, 99, 95]);
  });
});
