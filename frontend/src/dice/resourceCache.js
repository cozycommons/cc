import { useCallback, useEffect, useRef, useState } from 'react';

// Stale-while-revalidate cache for Dice reads. Pages render the last response
// for a key immediately and refresh it in the background, so moving between
// pages does not flash back to a loading state. Any Dice mutation clears it
// (see api.js), and a request started before that clear never writes back.
const MAX_ENTRIES = 120;
const entries = new Map();
const inflight = new Map();
let generation = 0;

export function peekDiceResource(key) {
  return key != null && entries.has(key) ? entries.get(key) : undefined;
}

export function writeDiceResource(key, data) {
  if (key == null || data === undefined) return;
  entries.delete(key);
  entries.set(key, data);
  while (entries.size > MAX_ENTRIES) entries.delete(entries.keys().next().value);
}

export function findDiceResource(predicate) {
  for (const [key, data] of entries) {
    const found = predicate(data, key);
    if (found !== undefined) return found;
  }
  return undefined;
}

export function invalidateDiceResources() {
  generation += 1;
  entries.clear();
  inflight.clear();
}

export function loadDiceResource(key, load) {
  const pending = inflight.get(key);
  if (pending && pending.generation === generation) return pending.promise;
  const started = generation;
  const promise = Promise.resolve()
    .then(load)
    .then((data) => {
      if (generation === started) writeDiceResource(key, data);
      return data;
    })
    .finally(() => {
      if (inflight.get(key)?.promise === promise) inflight.delete(key);
    });
  inflight.set(key, { generation: started, promise });
  return promise;
}

// Like useState for a fetched value: returns [data, setData]. `data` starts as
// the cached value (or null) and is replaced by the fresh response. On a failed
// refresh it keeps what is on screen, or falls back to `fallback` when nothing
// was shown yet. Pass `enabled: false` (or a null key) to skip the request.
export function useDiceResource(key, load, { fallback = null, enabled = true } = {}) {
  const [state, setState] = useState(() => ({ key, data: peekDiceResource(key) ?? null }));
  let current = state;
  if (state.key !== key) {
    current = { key, data: peekDiceResource(key) ?? null };
    setState(current);
  }
  const loadRef = useRef(load);
  loadRef.current = load;
  const fallbackRef = useRef(fallback);
  fallbackRef.current = fallback;

  useEffect(() => {
    if (!enabled || key == null) return undefined;
    let cancelled = false;
    loadDiceResource(key, () => loadRef.current())
      .then((data) => {
        if (!cancelled) setState({ key, data });
      })
      .catch(() => {
        if (cancelled) return;
        setState((previous) => (previous.key === key && previous.data != null
          ? previous
          : { key, data: fallbackRef.current }));
      });
    return () => {
      cancelled = true;
    };
  }, [key, enabled]);

  const setData = useCallback((next) => {
    setState((previous) => {
      const data = typeof next === 'function' ? next(previous.key === key ? previous.data : null) : next;
      writeDiceResource(key, data);
      return { key, data };
    });
  }, [key]);

  return [current.data, setData];
}
