import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanSnapshot, FALLBACK_URL, loadSnapshot } from './source.js';

const base = {
  version: 'public-v1', generated_at: '2026-10-24T15:00:00Z', matchup: { id: 1, ends: '2026-10-25' }, label: 'x',
  matchups: [{ home: { name: 'A' }, away: { name: 'B' }, scores: [1, 2], projected_totals: [3, 4], chance: 40,
    days: [{ date: '2026-10-20', state: 'final', actual: [1, 2], expected: [null, null], games: [null, null] },
      { date: '2026-10-21', state: 'projected', actual: null, expected: [2, 2], games: [5, 5] }], odds_history: [] }],
};

describe('cleanSnapshot', () => {
  it('keeps valid matchups, including finals without a recorded projection', () => {
    expect(cleanSnapshot(base).matchups[0].unavailable).toBeUndefined();
  });

  it('turns a malformed matchup into "not available" instead of crashing', () => {
    const data = { ...base, matchups: [{ home: { name: 'A' }, away: { name: 'B' }, scores: [1] }, { nope: true }] };
    expect(cleanSnapshot(data).matchups).toEqual([{ home: { name: 'A' }, away: { name: 'B' }, unavailable: true }]);
  });

  it('marks a matchup with duplicate or unordered dates unavailable', () => {
    const days = [base.matchups[0].days[1], base.matchups[0].days[0]];
    expect(cleanSnapshot({ ...base, matchups: [{ ...base.matchups[0], days }] }).matchups[0].unavailable).toBe(true);
  });

  it('rejects snapshots without the header fields', () => {
    expect(cleanSnapshot({ ...base, matchup: null })).toBeNull();
    expect(cleanSnapshot({ ...base, version: 'v2' })).toBeNull();
  });
});

describe('loadSnapshot', () => {
  afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

  it('moves on to the interim host when the API stalls', async () => {
    const stalled = (url, { signal }) => new Promise((resolve, reject) => {
      if (url === FALLBACK_URL) resolve({ status: 200, ok: true, json: async () => base });
      else if (signal.aborted) reject(Object.assign(new Error('timeout'), { name: 'TimeoutError' }));
    });
    vi.stubGlobal('fetch', vi.fn(stalled));
    const timeout = vi.spyOn(AbortSignal, 'timeout').mockImplementation(() => AbortSignal.abort());
    expect((await loadSnapshot('https://api.example.test')).matchup.id).toBe(1);
    timeout.mockRestore();
  });

  it('uses only the interim host when the API URL is unavailable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status: 200, ok: true, json: async () => base }));
    expect((await loadSnapshot(null)).matchup.id).toBe(1);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe(FALLBACK_URL);
  });
});
