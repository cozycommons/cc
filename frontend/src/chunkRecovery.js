const RELOAD_KEY = `cc-chunk-reload-attempted:${__APP_BUILD_ID__}`;

export function isChunkLoadError(error) {
  return error?.name === 'ChunkLoadError' || /ChunkLoadError|Failed to fetch dynamically imported module|Importing a module script failed|error loading dynamically imported module/i.test(error?.message || '');
}

// Persist before reloading: a fresh document must not retry the same failure.
// If storage is unavailable, leave the error visible instead of risking a loop.
export function recoverChunkLoad(error, { storage = () => window.sessionStorage, reload = () => window.location.reload(), buildId = __APP_BUILD_ID__ } = {}) {
  if (!isChunkLoadError(error)) return false;
  try {
    const store = storage();
    const key = buildId === __APP_BUILD_ID__ ? RELOAD_KEY : `cc-chunk-reload-attempted:${buildId}`;
    if (store.getItem(key)) return false;
    store.setItem(key, '1');
    if (store.getItem(key) !== '1') return false;
  } catch {
    return false;
  }
  reload();
  return true;
}

export function installChunkRecovery(target = window, recover = recoverChunkLoad) {
  const listener = event => {
    if (recover(event.payload)) event.preventDefault();
  };
  target.addEventListener('vite:preloadError', listener);
  return () => target.removeEventListener('vite:preloadError', listener);
}
