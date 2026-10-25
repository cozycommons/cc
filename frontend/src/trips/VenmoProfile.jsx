import React, { useEffect, useState } from 'react';
import { venmoProfile } from './venmo.js';

export default function VenmoProfile({ handle, request, debounce = 0 }) {
  const [state, setState] = useState({ handle: '', loading: true });
  const [failedPhoto, setFailedPhoto] = useState('');
  useEffect(() => {
    if (!handle) return;
    let current = true;
    const timer = setTimeout(async () => {
      let profile;
      try { profile = await request(`/venmo/profile?handle=${encodeURIComponent(handle)}`); } catch { profile = { found: false }; }
      if (current) setState({ ...profile, handle, loading: false });
    }, debounce);
    return () => { current = false; clearTimeout(timer); };
  }, [handle, request, debounce]);
  if (!handle) return null;
  const loading = state.handle !== handle || state.loading;
  const found = !loading && state.found;
  let photo;
  try { const url = new URL(state.photoUrl); if (url.protocol === 'https:' && url.host === 'pics-v3.venmo.com') photo = url.href; } catch { /* Initials fallback. */ }
  const name = found ? state.displayName : `@${handle}`;
  return <div className="trips-venmo-preview">
    <a className="trips-venmo-card" href={venmoProfile(handle)} target="_blank" rel="noopener noreferrer" aria-label={`${found ? `${name}, ` : ''}@${handle}, opens Venmo profile`}>
      <span className="trips-venmo-avatar">{found && photo && failedPhoto !== photo
        ? <img src={photo} alt="" referrerPolicy="no-referrer" onError={() => setFailedPhoto(photo)} />
        : <span>{found ? state.initials || name.slice(0, 1) : handle.slice(0, 1).toUpperCase()}</span>}</span>
      <span className="trips-venmo-identity"><span className="trips-venmo-badge">Venmo ↗</span><strong>{name}</strong>{found && <span>@{handle}</span>}</span>
    </a>
    <p className="trips-muted trips-small" role="status">{loading ? 'Finding profile…' : found ? state.active === false ? 'This profile isn’t active. Check the handle.' : '' : 'Preview unavailable. Open the profile on Venmo.'}</p>
  </div>;
}
