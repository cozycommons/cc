import { getUrl } from '../api.js';
import { getClient } from '../supabase.js';
import { getSessionId } from './sessionId.js';

// Fire-and-forget pageview beacon for routes with nothing else fetched from the
// backend on load (most SPA-only pages). Never throws and never blocks render --
// analytics is best-effort and must not affect the page it's tracking.
export async function trackPageview({ app, label, path }) {
  try {
    const base = await getUrl();
    const headers = { 'Content-Type': 'application/json' };
    const sessionId = getSessionId();
    if (sessionId) headers['X-Session-Id'] = sessionId;
    try {
      const { data: { session } = {} } = await getClient().auth.getSession();
      if (session?.access_token) headers.Authorization = `Bearer ${session.access_token}`;
    } catch {
      // No signed-in session available; proceed anonymously.
    }
    await fetch(`${base}/track/pageview`, {
      method: 'POST',
      headers,
      body: JSON.stringify({ app, label, path: path || (typeof window !== 'undefined' ? window.location.pathname : undefined) }),
      keepalive: true,
    });
  } catch {
    // Analytics failures should never surface to the user.
  }
}
