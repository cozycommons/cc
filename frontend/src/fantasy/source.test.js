import { afterEach, describe, expect, it, vi } from 'vitest';
import { cachedSnapshot, cleanSnapshot, FALLBACK_URL, laNoon, loadSnapshot } from './source.js';
import { SNAPSHOT_V2 } from './fixture.js';

const copy = () => structuredClone(SNAPSHOT_V2);

describe('cleanSnapshot', () => {
  it('turns a public-v2 snapshot into teams, matchups and the season race', () => {
    const data = cleanSnapshot(copy());
    expect(data.teams.size).toBe(4);
    expect(data.matchups.map(m => m.key)).toEqual(['1-2', '3-4']);
    expect(data.matchups[0].home.name).toBe('Harbor Hoopers');
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

  it('resolves only content-addressed public logo paths against the API', () => {
    const raw = copy();
    raw.teams[0].logo = '/espn/public/logos/' + 'a'.repeat(64);
    expect(cleanSnapshot(raw, 'https://api.example.test').teams.get(1).logo).toBe('https://api.example.test' + raw.teams[0].logo);
    expect(cleanSnapshot(raw, '/api').teams.get(1).logo).toBe('/api' + raw.teams[0].logo);
    raw.teams[0].logo = '//evil.example/logo.png';
    expect(cleanSnapshot(raw, 'https://api.example.test').teams.get(1).logo).toBeNull();
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

  it('anchors daily odds at Los Angeles noon and treats a null timestamp as daily', () => {
    expect(new Date(laNoon('2026-10-23')).toISOString()).toBe('2026-10-23T19:00:00.000Z');  // PDT
    expect(new Date(laNoon('2026-12-01')).toISOString()).toBe('2026-12-01T20:00:00.000Z');  // PST
    const snap = copy();
    snap.matchups[0].odds_history = [
      { date: '2026-10-23', chance: 40, at: null },
      { date: '2026-10-23', chance: 60, at: '2026-10-23T15:00:00Z' },
    ];
    const odds = cleanSnapshot(snap).matchups[0];
    expect(odds.unavailable).toBeFalsy();
    expect(odds.odds_history.map(p => p.chance)).toEqual([60, 40]);  // 8am PDT capture comes before the noon daily point
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
  afterEach(() => { localStorage.clear(); vi.unstubAllGlobals(); });

  it('keeps the last good public payload across failed and empty loads', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status: 200, ok: true, json: async () => copy() }));
    await loadSnapshot('https://cache.example.test');
    expect(cachedSnapshot('https://cache.example.test').matchup.id).toBe(1);
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    expect((await loadSnapshot('https://cache.example.test')).matchup.id).toBe(1);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status: 404, ok: false }));
    expect((await loadSnapshot('https://cache.example.test')).matchup.id).toBe(1);
    expect(await loadSnapshot('https://other.example.test')).toBeNull();
  });

  it('does not replace good data with malformed or wholly unavailable matchups', async () => {
    const fetcher = vi.fn().mockResolvedValue({ status: 200, ok: true, json: async () => copy() });
    vi.stubGlobal('fetch', fetcher);
    await loadSnapshot(null);
    const broken = copy();
    broken.matchups.forEach(match => { match.unavailable = true; });
    fetcher.mockResolvedValue({ status: 200, ok: true, json: async () => broken });
    expect((await loadSnapshot(null)).matchups.some(match => !match.unavailable)).toBe(true);
    fetcher.mockResolvedValue({ status: 200, ok: true, json: async () => ({ version: 'bad' }) });
    expect((await loadSnapshot(null)).matchup.id).toBe(1);
  });

  it('works when storage is blocked and rejects corrupt saved data', async () => {
    localStorage.setItem(`fantasy:last-good:v1:${FALLBACK_URL}`, '{');
    expect(cachedSnapshot(null)).toBeNull();
    const storage = vi.spyOn(Storage.prototype, 'setItem').mockImplementation(() => { throw new Error('quota'); });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status: 200, ok: true, json: async () => copy() }));
    expect((await loadSnapshot(null)).matchup.id).toBe(1);
    storage.mockRestore();
  });

  it('does not recover a cancelled request from storage', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status: 200, ok: true, json: async () => copy() }));
    await loadSnapshot(null);
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('Aborted', 'AbortError')));
    await expect(loadSnapshot(null, AbortSignal.abort())).rejects.toMatchObject({ name: 'AbortError' });
  });

  it('falls back to the interim host when the API has nothing', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ status: 404, ok: false })
      .mockResolvedValueOnce({ status: 200, ok: true, json: async () => copy() }));
    expect((await loadSnapshot('https://api.example.test')).matchup.id).toBe(1);
    expect(fetch.mock.calls[1][0]).toBe(FALLBACK_URL);
  });

  it('does not retry a caller cancellation', async () => {
    const controller = new AbortController();
    controller.abort();
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('cancelled', 'AbortError')));
    await expect(loadSnapshot(null, controller.signal)).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('retries a timeout while reading the response body', async () => {
    vi.stubGlobal('fetch', vi.fn()
      .mockResolvedValueOnce({ status: 200, ok: true, json: async () => { throw new DOMException('timed out', 'TimeoutError'); } })
      .mockResolvedValueOnce({ status: 200, ok: true, json: async () => copy() }));
    expect((await loadSnapshot(null)).matchup.id).toBe(1);
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('stops after two timeouts', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new DOMException('timed out', 'TimeoutError')));
    await expect(loadSnapshot(null)).rejects.toThrow('Predictions unavailable');
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('does not retry HTTP errors', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue({ status: 500, ok: false }));
    await expect(loadSnapshot(null)).rejects.toThrow('Predictions unavailable');
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('uses a 30-second header deadline, retries once, then falls back', async () => {
    vi.useFakeTimers();
    vi.stubGlobal('fetch', vi.fn(url => url === FALLBACK_URL
      ? Promise.resolve({ status: 200, ok: true, json: async () => copy() }) : new Promise(() => {})));
    try {
      const pending = loadSnapshot('https://api.example.test');
      await vi.advanceTimersByTimeAsync(29999);
      expect(fetch).toHaveBeenCalledTimes(1);
      await vi.advanceTimersByTimeAsync(30001);
      expect((await pending).matchup.id).toBe(1);
      expect(fetch).toHaveBeenCalledTimes(3);
    } finally { vi.useRealTimers(); }
  });
});

const encoder = new TextEncoder();
const encoded = value => encoder.encode(value);
const response = (stream, type = 'application/json') => ({ status: 200, ok: true,
  headers: new Headers({ 'content-type': type }), body: stream });
const lines = () => {
  const raw = copy();
  const { matchups, season, ...snapshot } = raw;
  return [
    { type: 'meta', total_matchups: matchups.length, snapshot,
      slots: matchups.map(m => ({ key: `${m.home}-${m.away}`, home: m.home, away: m.away })), season_available: true },
    ...matchups.map(matchup => ({ type: 'matchup', matchup })),
    { type: 'season', season }, { type: 'done' },
  ].map(line => JSON.stringify(line) + '\n');
};

describe('streaming predictions', () => {
  afterEach(() => { localStorage.clear(); vi.unstubAllGlobals(); vi.useRealTimers(); });

  it('keeps receiving for longer than 60 seconds while bytes keep arriving', async () => {
    vi.useFakeTimers();
    const body = JSON.stringify(copy());
    let controller;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(new ReadableStream({ start(c) { controller = c; } }))));
    const events = [];
    const pending = loadSnapshot(null, undefined, event => events.push(event));
    await vi.advanceTimersByTimeAsync(0);
    for (let i = 0; i < 5; i++) {
      await vi.advanceTimersByTimeAsync(15000);
      controller.enqueue(encoded(body.slice(i * 20, (i + 1) * 20)));
      await vi.advanceTimersByTimeAsync(0);
    }
    controller.enqueue(encoded(body.slice(100))); controller.close();
    expect((await pending).matchup.id).toBe(1);
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(events.at(-1).done).toBe(true);
  });

  it('retries a mid-body stall after 20 seconds without bytes, once only', async () => {
    vi.useFakeTimers();
    const cancel = vi.fn();
    let controller;
    const first = new ReadableStream({ start(c) { controller = c; }, cancel });
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(first))
      .mockResolvedValueOnce(response(new ReadableStream({ start(c) { c.enqueue(encoded(JSON.stringify(copy()))); c.close(); } }))));
    const pending = loadSnapshot(null);
    await vi.advanceTimersByTimeAsync(0);
    controller.enqueue(encoded('{'));
    await vi.advanceTimersByTimeAsync(19999);
    expect(fetch).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect((await pending).matchup.id).toBe(1);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(cancel).toHaveBeenCalledTimes(1);
  });

  it('does not treat empty chunks as progress and stops after the second idle deadline', async () => {
    vi.useFakeTimers();
    const controllers = [];
    vi.stubGlobal('fetch', vi.fn(() => Promise.resolve(response(new ReadableStream({ start(c) { controllers.push(c); } })))));
    const pending = loadSnapshot(null);
    const failure = expect(pending).rejects.toThrow('Predictions unavailable');
    await vi.advanceTimersByTimeAsync(0);
    await vi.advanceTimersByTimeAsync(15000);
    controllers[0].enqueue(new Uint8Array());
    await vi.advanceTimersByTimeAsync(5000);
    expect(fetch).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(20000);
    await failure;
    expect(fetch).toHaveBeenCalledTimes(2);
  });

  it('publishes each matchup before EOF, then caches only a complete stream', async () => {
    let controller;
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(new ReadableStream({ start(c) { controller = c; } }), 'application/x-ndjson')));
    const events = [];
    const pending = loadSnapshot('https://stream.example.test', undefined, event => events.push(event));
    const records = lines();
    // Byte boundaries may split both a JSON line and a multi-byte character.
    controller.enqueue(encoded(records[0] + records[1]));
    await vi.waitFor(() => expect(events.at(-1)?.matchups).toHaveLength(1));
    expect(events.at(-1).done).toBe(false);
    expect(events.at(-1).meta.totalMatchups).toBe(2);
    expect(events.at(-1).meta.slots).toHaveLength(2);
    expect(cachedSnapshot('https://stream.example.test')).toBeNull();
    for (const line of records.slice(2)) for (const byte of encoded(line)) controller.enqueue(Uint8Array.of(byte));
    controller.close();
    const final = await pending;
    expect(final.matchups).toHaveLength(2);
    expect(final.season).not.toBeNull();
    expect(events.at(-1).done).toBe(true);
    expect(cachedSnapshot('https://stream.example.test').matchups).toHaveLength(2);
  });

  it('does not cache a truncated stream and falls back to JSON', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(response(new ReadableStream({ start(c) {
      c.enqueue(encoded(lines().slice(0, 2).join(''))); c.close();
    } }), 'application/x-ndjson')).mockResolvedValueOnce({ status: 200, ok: true, json: async () => copy() }));
    expect((await loadSnapshot('https://stream.example.test')).matchups).toHaveLength(2);
    expect(fetch).toHaveBeenCalledTimes(2);
    expect(fetch.mock.calls[1][0]).toBe(FALLBACK_URL);
  });

  it('cancels a body read promptly without a retry or caching partial rows', async () => {
    const controller = new AbortController();
    const cancel = vi.fn();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(response(new ReadableStream({ cancel }))));
    const pending = loadSnapshot(null, controller.signal);
    await vi.waitFor(() => expect(fetch).toHaveBeenCalledTimes(1));
    controller.abort();
    await expect(pending).rejects.toMatchObject({ name: 'AbortError' });
    expect(fetch).toHaveBeenCalledTimes(1);
    expect(cachedSnapshot(null)).toBeNull();
  });
});
