const local = ['localhost', '127.0.0.1'].includes(window.location.hostname);
const base = local ? import.meta.env.VITE_CROWD_SET_API_URL || 'http://127.0.0.1:8010' : window.location.origin;

export function endpoint(path = '') {
  const url = new URL(base);
  if (local ? url.protocol !== 'http:' || !['localhost', '127.0.0.1'].includes(url.hostname) : url.protocol !== 'https:' || url.origin !== window.location.origin) {
    throw new Error('Invalid Crowd Set API URL.');
  }
  return `${base.replace(/\/$/, '')}/crowd-set/sets${path}`;
}

export async function request(path = '', options = {}) {
  const headers = new Headers(options.headers);
  if (!local) {
    const { auth } = await import('../supabase');
    const session = await auth.getSession();
    if (!session) throw Object.assign(new Error('Sign in to continue.'), { status: 401 });
    headers.set('Authorization', `Bearer ${session.access_token}`);
  }
  const response = await fetch(endpoint(path), { ...options, headers, cache: 'no-store' });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    const detail = typeof body.detail === 'string' ? body.detail : Array.isArray(body.detail) ? body.detail.map((issue) => issue.msg).filter(Boolean).join(' ') : '';
    throw Object.assign(new Error(detail || `Request failed (${response.status})`), { status: response.status });
  }
  return response.status === 204 ? null : response.json();
}

export const getLimits = () => request('?limits=true');
