import { afterEach, expect, it, vi } from 'vitest';
import { installChunkRecovery, isChunkLoadError, recoverChunkLoad } from './chunkRecovery.js';
afterEach(() => { sessionStorage.clear(); });
it.each([
  new Error('Failed to fetch dynamically imported module: /assets/old.js'),
  Object.assign(new Error('Loading chunk 1 failed'), { name: 'ChunkLoadError' }),
  new Error('Importing a module script failed.'),
])('reloads exactly once across fresh document/module instances for %s', async error => {
  const reload = vi.fn();
  expect(recoverChunkLoad(error, { reload })).toBe(true);
  expect(recoverChunkLoad(error, { reload })).toBe(false);
  vi.resetModules();
  const freshDocument = await import('./chunkRecovery.js');
  expect(freshDocument.recoverChunkLoad(error, { reload })).toBe(false);
  expect(reload).toHaveBeenCalledOnce();
});
it('does not reload for unrelated errors or inaccessible/nonpersistent storage', () => {
  const reload = vi.fn();
  expect(isChunkLoadError(new Error('fetch failed'))).toBe(false);
  expect(recoverChunkLoad(new Error('render failed'), { reload })).toBe(false);
  const error = new Error('Failed to fetch dynamically imported module');
  for (let attempt = 0; attempt < 3; attempt++) {
    expect(recoverChunkLoad(error, { reload, storage: () => { throw new Error('denied'); } })).toBe(false);
    expect(recoverChunkLoad(error, { reload, storage: () => ({ getItem: () => null, setItem() {} }) })).toBe(false);
  }
  expect(reload).not.toHaveBeenCalled();
});
it('handles Vite preload errors using the same persistent guard', () => {
  const reload = vi.fn();
  const remove = installChunkRecovery(window, error => recoverChunkLoad(error, { reload }));
  const dispatch = () => {
    const event = new Event('vite:preloadError', { cancelable: true });
    event.payload = new Error('Failed to fetch dynamically imported module');
    window.dispatchEvent(event);
    return event.defaultPrevented;
  };
  expect(dispatch()).toBe(true);
  expect(dispatch()).toBe(false);
  remove();
  expect(reload).toHaveBeenCalledOnce();
});
it('gives a new deployed build one recovery attempt without resetting the old budget', () => {
  const reload = vi.fn();
  const error = new Error('Failed to fetch dynamically imported module');
  expect(recoverChunkLoad(error, { reload, buildId: 'build-a' })).toBe(true);
  expect(recoverChunkLoad(error, { reload, buildId: 'build-a' })).toBe(false);
  expect(recoverChunkLoad(error, { reload, buildId: 'build-b' })).toBe(true);
  expect(recoverChunkLoad(error, { reload, buildId: 'build-b' })).toBe(false);
  expect(recoverChunkLoad(error, { reload, buildId: 'build-a' })).toBe(false);
  expect(reload).toHaveBeenCalledTimes(2);
});
