const key = 'crowdset:player';

export function readPlayerPreferences() {
  let saved;
  try { saved = JSON.parse(localStorage.getItem(key)); } catch { /* Storage can be disabled. */ }
  return {
    volume: typeof saved?.volume === 'number' && Number.isFinite(saved.volume) && saved.volume >= 0 && saved.volume <= 1 ? saved.volume : 1,
    muted: saved?.muted === true,
    theater: saved?.theater === true,
  };
}

export function savePlayerPreferences(values) {
  try { localStorage.setItem(key, JSON.stringify({ ...readPlayerPreferences(), ...values })); } catch { /* Playback still works without storage. */ }
}
