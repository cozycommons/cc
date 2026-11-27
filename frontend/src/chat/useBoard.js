import { useEffect, useState } from 'react';
import { boardPath, boardRequest, currentView, listChannels, viewHref } from './board.js';

export function useNavigation() {
  const [route, setRoute] = useState(currentView);
  useEffect(() => {
    const sync = () => setRoute(currentView());
    window.addEventListener('popstate', sync);
    return () => window.removeEventListener('popstate', sync);
  }, []);
  function navigate(next) {
    window.history.pushState(null, '', viewHref(next));
    setRoute(next);
  }
  return [route, navigate];
}

export function useLiveBoard(onUpdate) {
  const [live, setLive] = useState(false);
  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    let retry;
    async function follow(cursor) {
      try {
        const result = await boardRequest(cursor
          ? boardPath('/events', { after: cursor, wait: 20 })
          : '/events?last=1', { signal });
        if (signal.aborted) return;
        setLive(true);
        if (result.events.length) onUpdate();
        void follow(result.cursor);
      } catch {
        if (signal.aborted) return;
        setLive(false);
        retry = setTimeout(() => { onUpdate(); void follow(cursor); }, 5000);
      }
    }
    void follow();
    return () => { controller.abort(); clearTimeout(retry); };
  }, [onUpdate]);
  return live;
}

export function useBoardRead(key, revision, read) {
  const [state, setState] = useState({ key: null, value: null, error: '' });
  useEffect(() => {
    if (key == null) return;
    const controller = new AbortController();
    read(key, controller.signal).then(
      value => { if (!controller.signal.aborted) setState({ key, value, error: '' }); },
      error => { if (!controller.signal.aborted) setState(previous => ({ key, value: previous.key === key ? previous.value : null, error: error.message })); },
    );
    return () => controller.abort();
  }, [key, revision, read]);
  return key != null && key === state.key ? state : { value: null, error: '' };
}

export const readChannels = (_, signal) => listChannels(signal);
export const readThread = (id, signal) => boardRequest('/messages/' + encodeURIComponent(id) + '?limit=100', { signal });

export async function readTimeline(key, signal) {
  const query = JSON.parse(key);
  const options = { signal };
  if (query.tasks) {
    const result = await boardRequest(boardPath('/tasks', { state: query.filter ? 'all' : 'open', limit: 100 }), options);
    return { rows: result.tasks, older: null };
  }
  if (query.view == null && !query.filter) {
    const result = await boardRequest('/events?last=100', options);
    const messages = new Map();
    for (const event of result.events) {
      const message = event.message;
      if (!message) continue;
      if (message.deleted) messages.delete(message.id);
      else messages.set(message.id, message);
    }
    return {
      rows: [...messages.values()].sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt)).map(message => ({ message })),
      older: null,
    };
  }
  const result = await boardRequest(boardPath('/threads', {
    channel: query.view == null ? null : query.view,
    text: query.filter || null,
    limit: 40,
    before: query.older,
  }), options);
  return { rows: result.threads, older: result.older };
}
