const SESSION_ID_KEY = 'jk_session_id';

// One id per browser tab session (sessionStorage clears on tab close), used
// only to group analytics events server-side -- not an auth concept. Shared
// across all frontend sub-apps within the same origin.
export function getSessionId() {
  if (typeof window === 'undefined') return null;
  try {
    let id = window.sessionStorage.getItem(SESSION_ID_KEY);
    if (!id) {
      id = crypto.randomUUID();
      window.sessionStorage.setItem(SESSION_ID_KEY, id);
    }
    return id;
  } catch {
    return null;
  }
}
