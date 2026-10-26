import { getClient } from '../supabase.js';
import { getUrl } from '../api.js';

export async function adminRequest(path, { body, ...options } = {}) {
  const { data: { session } = {} } = await getClient().auth.getSession();
  if (!session) throw Object.assign(new Error('Sign in to continue.'), { status: 401 });
  const response = await fetch(`${getUrl()}/admin${path}`, {
    ...options, cache: 'no-store', headers: { Authorization: `Bearer ${session.access_token}`, 'Content-Type': 'application/json' },
    ...(body ? { body: JSON.stringify(body) } : {}),
  });
  if (!response.ok) {
    const data = await response.json().catch(() => ({}));
    throw Object.assign(new Error(typeof data.detail === 'string' ? data.detail : 'Request failed.'), { status: response.status });
  }
  return response.status === 204 ? null : response.json();
}
