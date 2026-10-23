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
    // The request may or may not have reached the server.
    const uncertain = new Error(method === 'GET'
      ? 'Could not reach Cozy Trips. Check your connection and try again.'
      : 'Could not confirm this saved. Check your connection, then save again — it won’t be duplicated.');
    uncertain.uncertain = true;
    throw uncertain;
  }
  let result;
  try {
    result = await response.json();
  } catch {
    if (response.ok) {
      // The server answered but the body was cut off: the change may have saved.
      const uncertain = new Error(method === 'GET' ? 'Cozy Trips sent an incomplete response. Try again.'
        : 'Could not confirm this saved. Check your connection, then save again — it won’t be duplicated.');
      uncertain.uncertain = true;
      throw uncertain;
    }
    result = {};
  }
  if (!response.ok) {
    const detail = result.detail;
    const message = typeof detail === 'string' ? detail
      : Array.isArray(detail) && typeof detail[0]?.msg === 'string' ? detail[0].msg.replace(/^Value error, /, '')
        : 'Check the amounts and required fields, then try again.';
    const failure = new Error(message);
    failure.status = response.status;
    throw failure;
  }
  return result;
}
