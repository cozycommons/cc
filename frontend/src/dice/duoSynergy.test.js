import { describe, expect, it } from 'vitest';
import { isOnExpected, synergyDescription } from './duoSynergy.js';

describe('duo comparison wording', () => {
  it.each([-0.049, 0, 0.049])('treats %s as right on expected', (difference) => {
    const synergy = { wins_above_expected: difference };
    expect(isOnExpected(synergy)).toBe(true);
    expect(synergyDescription(synergy)).toBe('Right on expected');
    expect(synergyDescription(synergy, { short: true })).toBe('Right on expected');
  });
  it.each([[1, '1.0 win over expected'], [-1, '1.0 win under expected'], [2.44, '2.4 wins over expected'], [-3.14, '3.1 wins under expected']])('rounds and uses the appropriate unit for %s', (difference, wording) => {
    expect(synergyDescription({ wins_above_expected: difference })).toBe(wording);
  });
  it.each([0.05, -0.05])('keeps the neutral boundary strict (%s)', (difference) => {
    expect(isOnExpected({ wins_above_expected: difference })).toBe(false);
  });
});
