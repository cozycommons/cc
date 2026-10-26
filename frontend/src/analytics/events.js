import { resolveRuntimeServiceUrl } from '../runtimeConfig.js';

const KEY = 'cc_analytics_session_v1';
const EXPIRES = 30 * 60 * 1000;
let fallback;
let pending = Promise.resolve();

export function projectForPath(path) {
  if (path === '/') return 'commons';
  return ['dice', 'trips', 'crowdset', 'fantasy'].find((project) => path === `/${project}` || path.startsWith(`/${project}/`)) || null;
}

export function sessionForActivity(now = Date.now()) {
  let record;
  try { record = JSON.parse(localStorage.getItem(KEY)) || fallback; } catch { record = fallback; }
  if (!record?.id || !Number.isFinite(record.last) || now - record.last >= EXPIRES || now < record.last) {
    record = { id: crypto.randomUUID(), last: now };
  }
  record.last = now;
  fallback = record;
  try { localStorage.setItem(KEY, JSON.stringify(record)); } catch { /* Storage is optional. */ }
  return record.id;
}

export function trackEvent({ project, eventType = 'action', eventName, path = window.location.pathname, metadata = {} }) {
  const eventId = crypto.randomUUID();
  const report = async () => {
    try {
      const sessionId = navigator.locks
        ? await navigator.locks.request(KEY, () => sessionForActivity())
        : sessionForActivity();
      const { getClient } = await import('../supabase.js');
      const { data: { session } = {} } = await getClient().auth.getSession();
      const headers = { 'Content-Type': 'application/json' };
      if (session?.access_token) headers.Authorization = `Bearer ${session.access_token}`;
      const body = JSON.stringify({ schema_version: 1, event_id: eventId, project, event_type: eventType, event_name: eventName, session_id: sessionId, path, metadata });
      await fetch(`${resolveRuntimeServiceUrl(import.meta.env.VITE_API_URL)}/track/events`, { method: 'POST', headers, body, keepalive: true, signal: AbortSignal.timeout(5000) });
    } catch { /* Telemetry must not affect product behavior. */ }
  };
  pending = pending.then(report, report);
  return pending;
}
