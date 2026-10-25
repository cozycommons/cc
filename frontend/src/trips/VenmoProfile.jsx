import React, { useEffect, useState } from 'react';
import { getUrl } from '../api.js';
import { venmoProfile } from './venmo.js';

export default function VenmoProfile({ handle, request, debounce = 0, confirmedName }) {
  const [state, setState] = useState({ handle: '', loading: true });
  const [failedPhoto, setFailedPhoto] = useState('');
  useEffect(() => {
    if (!handle) return;
    let current = true;
    const timer = setTimeout(async () => {
      let profile;
      try { profile = await request(`/venmo/profile?handle=${encodeURIComponent(handle)}`); } catch { profile = { found: false }; }
      if (current) { setState({ ...profile, handle, loading: false }); }
    }, debounce);
    return () => { current = false; clearTimeout(timer); };
  }, [handle, request, debounce]);
  if (!handle) return null;
  const loading = state.handle !== handle || state.loading;
  const found = !loading && state.found;
  const photo = typeof state.photoUrl === 'string' && state.photoUrl.startsWith('/venmo/photo?') ? `${getUrl()}${state.photoUrl}` : '';
  const name = found ? state.displayName : `@${handle}`;
  return <div className="trips-venmo-preview">
    <a className="trips-venmo-card" href={venmoProfile(handle)} target="_blank" rel="noopener noreferrer" aria-label={`${found ? `${name}, ` : ''}@${handle}, opens Venmo profile`}>
      <span className="trips-venmo-avatar">{found && photo && failedPhoto !== photo
        ? <img src={photo} alt="" referrerPolicy="no-referrer" onError={() => setFailedPhoto(photo)} />
        : <span>{found ? state.initials || name.slice(0, 1) : handle.slice(0, 1).toUpperCase()}</span>}</span>
      <span className="trips-venmo-identity"><span className="trips-venmo-badge">Venmo ↗</span><strong>{name}</strong>{found && <span>@{handle}</span>}</span>
    </a>
    {found && confirmedName && name !== confirmedName && <p className="trips-muted trips-small">Previously confirmed as {confirmedName}. Check the handle.</p>}
    <p className="trips-muted trips-small" role="status">{loading ? 'Finding profile…' : found ? state.active === false ? 'This profile isn’t active. Check the handle.' : '' : ''}</p>
  </div>;
}
