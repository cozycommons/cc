import { act, renderHook, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

function deferred() {
  let resolve;
  const promise = new Promise((done) => { resolve = done; });
  return { promise, resolve };
}
import {
  findDiceResource,
  invalidateDiceResources,
  loadDiceResource,
  peekDiceResource,
  useDiceResource,
  writeDiceResource,
} from './resourceCache.js';

describe('Dice resource cache', () => {
  it('renders the cached value at once and replaces it with the fresh response', async () => {
    writeDiceResource('games', ['old']);
    const response = deferred();
    const load = vi.fn(() => response.promise);

    const { result } = renderHook(() => useDiceResource('games', load, { fallback: [] }));

    expect(result.current[0]).toEqual(['old']);
    await act(async () => response.resolve(['new']));
    expect(result.current[0]).toEqual(['new']);
    expect(peekDiceResource('games')).toEqual(['new']);
  });

  it('keeps what is on screen when a refresh fails, and falls back when nothing was shown', async () => {
    writeDiceResource('cached', ['shown']);
    const failing = () => Promise.reject(new Error('offline'));

    const cached = renderHook(() => useDiceResource('cached', failing, { fallback: [] }));
    const empty = renderHook(() => useDiceResource('empty', failing, { fallback: [] }));

    await waitFor(() => expect(empty.result.current[0]).toEqual([]));
    expect(cached.result.current[0]).toEqual(['shown']);
    expect(peekDiceResource('empty')).toBeUndefined();
  });

  it('shares one request between concurrent readers of a key', async () => {
    const load = vi.fn(() => Promise.resolve(['games']));

    await Promise.all([loadDiceResource('shared', load), loadDiceResource('shared', load)]);

    expect(load).toHaveBeenCalledTimes(1);
  });

  it('never lets a request started before a mutation write stale data back', async () => {
    const response = deferred();
    const pending = loadDiceResource('stale', () => response.promise);

    invalidateDiceResources();
    response.resolve(['before the write']);
    await pending;

    expect(peekDiceResource('stale')).toBeUndefined();
  });

  it("switches to the new key without showing the previous key's data", async () => {
    writeDiceResource('profile:b', { id: 'b' });
    const load = vi.fn((key) => new Promise(() => key));
    const { result, rerender } = renderHook(({ key }) => useDiceResource(key, () => load(key)), {
      initialProps: { key: 'profile:a' },
    });
    expect(result.current[0]).toBeNull();

    rerender({ key: 'profile:b' });
    expect(result.current[0]).toEqual({ id: 'b' });
  });

  it('skips the request for a null key', () => {
    const load = vi.fn();
    const { result } = renderHook(() => useDiceResource(null, load));
    expect(result.current[0]).toBeNull();
    expect(load).not.toHaveBeenCalled();
  });

  it('finds a value across cached entries', () => {
    writeDiceResource('games:all', [{ id: 'g1', players: [] }]);
    expect(findDiceResource((data) => (Array.isArray(data) ? data.find((game) => game.id === 'g1') : undefined)))
      .toEqual({ id: 'g1', players: [] });
  });
});

describe('Dice resource cache invalidation', () => {
  it('runs keyless loads without caching them', async () => {
    const load = vi.fn(() => Promise.resolve({ duo: true }));
    await expect(loadDiceResource(null, load)).resolves.toEqual({ duo: true });
    await loadDiceResource(null, load);
    expect(load).toHaveBeenCalledTimes(2);
  });

  it('starts a fresh request after a mutation instead of reusing the stale one', async () => {
    const stale = deferred();
    const load = vi.fn()
      .mockImplementationOnce(() => stale.promise)
      .mockImplementationOnce(() => Promise.resolve(['after']));
    const first = loadDiceResource('tournament:t1', load);
    invalidateDiceResources();

    await expect(loadDiceResource('tournament:t1', load)).resolves.toEqual(['after']);
    stale.resolve(['before']);
    await first;

    expect(peekDiceResource('tournament:t1')).toEqual(['after']);
  });
});
