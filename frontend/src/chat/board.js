export async function boardRequest(path, { body, signal, file, profile } = {}) {
  const headers = new Headers({ 'x-chat-request': '1' });
  if (profile) headers.set('x-board-profile', profile);
  if (file) {
    headers.set('content-type', file.type || 'application/octet-stream');
    headers.set('x-board-filename', encodeURIComponent(file.name));
  } else if (body !== undefined) {
    headers.set('content-type', 'application/json');
  }
  const response = await fetch('/board' + path, {
    method: file || body !== undefined ? 'POST' : 'GET',
    headers,
    body: file || (body === undefined ? undefined : JSON.stringify(body)),
    signal,
  });
  if (response.ok) {
    return path.startsWith('/attachments/') ? response.blob() : response.json();
  }
  if (response.status === 401) {
    window.location.assign('/auth/sign-in?' + new URLSearchParams({ next: window.location.pathname + window.location.search }));
  }
  const refusal = await response.json().catch(() => null);
  throw new Error(refusal?.error?.message || 'Cozy Chat couldn’t complete the request.');
}

export function boardPath(path, query) {
  return path + '?' + new URLSearchParams(Object.entries(query).filter(([, value]) => value != null));
}

export function currentView() {
  const params = new URLSearchParams(window.location.search);
  return { view: params.get('channel') || null, thread: params.get('thread'), tasks: params.get('view') === 'tasks' };
}

export function viewHref({ view = null, tasks, thread }) {
  const params = new URLSearchParams();
  if (tasks) params.set('view', 'tasks');
  else if (view != null) params.set('channel', view);
  if (thread) params.set('thread', thread);
  return params.size ? '/?' + params : '/';
}

export async function listChannels(signal) {
  const all = [];
  let after;
  do {
    const result = await boardRequest(boardPath('/channels', { after }), { signal });
    all.push(...result.channels);
    after = result.next;
  } while (after);
  return all;
}
