import { describe, expect, it } from 'vitest';
import { equalShares, toMinor, weightedShares } from './money.js';

describe('trip money input', () => {
  it('parses decimal text without floating point rounding', () => {
    expect(toMinor('120.01')).toBe(12001);
    expect(toMinor('0.29')).toBe(29);
    expect(toMinor('12.5')).toBe(1250);
    expect(toMinor('0', true)).toBe(0);
  });
  it('accepts what people type on phones', () => {
    expect(toMinor('$12')).toBe(1200);
    expect(toMinor('1,250.50')).toBe(125050);
    expect(toMinor('.75')).toBe(75);
    expect(toMinor(' 9 ')).toBe(900);
    expect(toMinor('45,50')).toBe(4550);
    expect(toMinor('45,5')).toBe(4550);
  });
  it.each(['-1', '1.001', '1e3', 'NaN', '', '0', '10000000.01', '.', '1,2345', '1.2.3', '$'])('rejects invalid money %s', (value) => {
    expect(() => toMinor(value)).toThrow();
  });
  it('allocates every penny once, including amounts smaller than group size', () => {
    const people = [{ id: 'a' }, { id: 'b' }, { id: 'c' }];
    expect(equalShares(100, people)).toEqual({ a: 34, b: 33, c: 33 });
    expect(equalShares(1, people)).toEqual({ a: 1, b: 0, c: 0 });
  });
  it('matches the backend weighted split, including leftover pennies', () => {
    expect(weightedShares(1000, { a: 2, b: 1 })).toEqual({ a: 667, b: 333 });
    expect(weightedShares(100, { a: 1, b: 1, c: 1 })).toEqual({ a: 34, b: 33, c: 33 });
    expect(weightedShares(1, { a: 1, b: 3 })).toEqual({ a: 0, b: 1 });
    const big = weightedShares(999_999_999, { a: 7, b: 13, c: 1000 });
    expect(Object.values(big).reduce((x, y) => x + y, 0)).toBe(999_999_999);
  });
});
