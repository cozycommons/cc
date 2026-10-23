import { describe, expect, it } from 'vitest';
import { equalShares, toMinor } from './money.js';

describe('trip money input', () => {
  it('parses decimal text without floating point rounding', () => {
    expect(toMinor('120.01')).toBe(12001);
    expect(toMinor('0.29')).toBe(29);
    expect(toMinor('12.5')).toBe(1250);
    expect(toMinor('0', true)).toBe(0);
  });
  it.each(['-1', '1.001', '1e3', 'NaN', '', '0', '10000000.01'])('rejects invalid money %s', (value) => {
    expect(() => toMinor(value)).toThrow();
  });
  it('allocates every penny once, including amounts smaller than group size', () => {
    const people = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
    expect(equalShares(100, people)).toEqual({ a: 34, b: 33, c: 33 });
    expect(equalShares(1, people)).toEqual({ a: 1, b: 0, c: 0 });
  });
});
