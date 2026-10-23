import { getUrl } from '../api.js';

export async function tripRequest(supabase, path, method = 'GET', payload) {
  const { data, error } = await supabase.auth.getSession();
  if (error || !data.session) throw new Error('Please sign in again to continue.');
  let response;
  try {
    response = await fetch(`${getUrl()}/trips${path}`, {
      method,
      headers: { Authorization: `Bearer ${data.session.access_token}`, 'Content-Type': 'application/json' },
      ...(payload === undefined ? {} : { body: JSON.stringify(payload) }),
    });
  } catch {
    throw new Error('Could not reach Cozy Trips. Check your connection, then refresh the trip to check whether your change saved.');
  }
  const result = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = result.detail;
    const error = new Error(typeof detail === 'string' ? detail : 'Check the amounts and required fields, then try again.');
    error.status = response.status;
    throw error;
  }
  return result;
}
