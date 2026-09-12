import { describe, expect, it } from 'vitest';
import { COMMONS_PLAYER_COMPOSITIONS, getCommonsPlayerComposition } from './player-compositions.js';

describe('Commons player compositions', () => {
  it('defines three distinct original residents with the same atlas contract', () => {
    const compositions = Object.values(COMMONS_PLAYER_COMPOSITIONS);
    expect(compositions).toHaveLength(3);
    expect(new Set(compositions.map((composition) => composition.spritePath)).size).toBe(3);
    expect(compositions.every((composition) => (
      composition.frameWidth === 64
      && composition.frameHeight === 96
      && composition.frames === 16
      && composition.sourcePixelScale === 2
      && composition.directionRows.front === 3
      && composition.displayWidth === 30
      && composition.displayHeight === 46
    ))).toBe(true);
  });

  it('returns a stable null result for unknown cast members', () => {
    expect(getCommonsPlayerComposition('unknown')).toBeNull();
  });
});
