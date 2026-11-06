import React from 'react';
import { RefreshCw } from 'lucide-react';
import { useNow } from './live.js';

// Citi Bike rebuilds its feed about every minute; past this, its own data is old.
const SOURCE_STALE_S = 300;

export function ago(seconds) {
  if (seconds < 10) return 'just now';
  if (seconds < 60) return `${Math.round(seconds)} s ago`;
  return `${Math.round(seconds / 60)} min ago`;
}

const clock = (date) => date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', timeZone: 'America/New_York' });

// One line for how fresh the live data is: Citi Bike's own time, when this page
// last checked, and a refresh. A failed refresh says how old the data on screen is.
export default function Freshness({ state }) {
  const now = useNow();
  if (!state.data) return null;
  const feedAt = state.data.feed_updated_at ? new Date(state.data.feed_updated_at) : null;
  const sourceAge = feedAt ? (now - feedAt) / 1000 : null;
  const checked = (now - state.at) / 1000;
  const failed = state.status === 'error';
  const busy = state.status === 'refreshing' || state.status === 'loading';
  let text;
  if (failed) {
    text = `Couldn't refresh. Showing Citi Bike data from ${feedAt ? `${clock(feedAt)}, ${ago(sourceAge)}` : ago(checked)}.`;
  } else if (sourceAge != null && sourceAge > SOURCE_STALE_S) {
    text = `Citi Bike hasn't updated since ${clock(feedAt)}.`;
  } else {
    text = `Citi Bike data from ${feedAt ? clock(feedAt) : 'now'} · checked ${ago(checked)}`;
  }
  const warn = failed || (sourceAge != null && sourceAge > SOURCE_STALE_S);
  return (
    <p className={`bk-fresh${warn ? ' is-warn' : ''}`} role="status">
      <span>{text}</span>
      <button type="button" className="bk-fresh__refresh" onClick={state.refresh} disabled={busy}
        aria-label={failed ? 'Retry' : 'Refresh'}>
        <RefreshCw size={16} aria-hidden="true" className={busy ? 'is-spinning' : undefined} />
        <span>{failed ? 'Retry' : 'Refresh'}</span>
      </button>
    </p>
  );
}
