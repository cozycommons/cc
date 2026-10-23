// Keep one-use invitation secrets across the normal Google OAuth redirect.
// Storage restrictions must not crash the page or turn a completed join into an error.
export function readInvitation(tripId, hash = window.location.hash, storage = window.sessionStorage) {
  const token = new URLSearchParams(hash.slice(1)).get('invite') || '';
  try {
    if (token) storage.setItem(`cozy-trips-invite:${tripId}`, token);
    return token || storage.getItem(`cozy-trips-invite:${tripId}`) || '';
  } catch {
    return token;
  }
}

export function clearInvitation(tripId, storage = window.sessionStorage) {
  try { storage.removeItem(`cozy-trips-invite:${tripId}`); } catch { /* Joining already succeeded. */ }
}
