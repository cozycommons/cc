import { afterEach, describe, expect, it, vi } from 'vitest';
import { cleanSnapshot, FALLBACK_URL, loadSnapshot } from './source.js';
import { SNAPSHOT_V2 } from './fixture.js';

const copy = () => structuredClone(SNAPSHOT_V2);

describe('cleanSnapshot', () => {
  it('turns a public-v2 snapshot into teams, matchups and the season race', () => {
    const data = cleanSnapshot(copy());
    expect(data.teams.size).toBe(4);
    expect(data.matchups.map(m => m.key)).toEqual(['1-2', '3-4']);
    expect(data.matchups[0].home.name).toBe('Glass Cleaners');
    expect(data.season.modes.balanced).toHaveLength(4);
    expect(data.season.modes.balanced[0].team.id).toBe(1);
  });

  it('keeps only ESPN or embedded PNG logos', () => {
    const raw = copy();
    raw.teams[1].logo = 'https://evil.example/logo.png';
    const teams = cleanSnapshot(raw).teams;
    expect(teams.get(1).logo).toMatch(/^https:\/\/g\.espncdn\.com\//);
    expect(teams.get(2).logo).toBeNull();
    expect(teams.get(3).logo).toMatch(/^data:image\/png;base64,/);
  });

  it('marks a matchup unavailable when players appear on a projected day', () => {
    const raw = copy();
    raw.matchups[0].days.at(-1).players = [[{ id: 1, name: 'X', points: 1 }], []];
    expect(cleanSnapshot(raw).matchups[0].unavailable).toBe(true);
  });

  it('orders intraday odds by capture time and rejects bad timestamps', () => {
    const snap = copy();
    snap.matchups[0].odds_history = [
      { date: '2026-10-23', chance: 60, at: '2026-10-23T22:00:00Z' },
      { date: '2026-10-23', chance: 40, at: '2026-10-23T18:00:00Z' },
    ];
    expect(cleanSnapshot(snap).matchups[0].odds_history.map(p => p.chance)).toEqual([40, 60]);
    snap.matchups[0].odds_history[0].at = 'soon';
    expect(cleanSnapshot(snap).matchups[0].unavailable).toBe(true);
  });

  it('still renders older public-v1 snapshots', () => {
    const v1 = { version: 'public-v1', generated_at: 'x', matchup: { id: 1, ends: '2026-10-25' }, label: '',
      matchups: [{ home: { name: 'A' }, away: { name: 'B' }, scores: [1, 2], projected_totals: [3, 4], chance: 40,
        days: [{ date: '2026-10-21', state: 'projected', actual: null, expected: [2, 2], games: [5, 5] }], odds_history: [] }] };
    const data = cleanSnapshot(v1);
    expect(data.matchups[0].home.name).toBe('A');
    expect(data.season).toBeNull();
    expect(data.linkable).toBe(false);  // synthetic ids must never match Dice links
    expect(cleanSnapshot(structuredClone(SNAPSHOT_V2)).linkable).toBe(true);
  });

  it('drops a season whose modes do not cover every team', () => {
    const raw = copy();
    raw.season.modes = { balanced: raw.season.modes.balanced.slice(0, 2) };
    expect(cleanSnapshot(raw).season).toBeNull();
  });
});

describe('loadSnapshot', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('falls back to the interim host when the API has nothing', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ status: 404, ok: false })
      .mockResolvedValueOnce({ status: 200, ok: true, json: async () => copy() }));
    expect((await loadSnapshot('https://api.example.test')).matchup.id).toBe(1);
    expect(fetch.mock.calls[1][0]).toBe(FALLBACK_URL);
  });

  it('moves on to the interim host when the API stalls', async () => {
    vi.stubGlobal('fetch', vi.fn((url, { signal }) => (url === FALLBACK_URL
      ? Promise.resolve({ status: 200, ok: true, json: async () => copy() })
      : signal.aborted ? Promise.reject(Object.assign(new Error('timeout'), { name: 'TimeoutError' })) : new Promise(() => {}))));
    const timeout = vi.spyOn(AbortSignal, 'timeout').mockImplementation(() => AbortSignal.abort());
    expect((await loadSnapshot('https://api.example.test')).matchup.id).toBe(1);
    timeout.mockRestore();
  });
});
