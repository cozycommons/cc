import { useCallback, useEffect, useRef, useState } from 'react';
import { getUrl } from '../api.js';

export const REFRESH_MS = 60000;

export async function getJson(path, params = {}) {
  const query = new URLSearchParams(Object.entries(params).filter(([, v]) => v != null && v !== ''));
  const response = await fetch(`${getUrl()}/bikes/${path}${query.size ? `?${query}` : ''}`);
  if (response.status === 422) throw new Error('That place is outside the Citi Bike area.');
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(body?.detail || 'Could not reach Citi Bike. Try again.');
  return body;
}

// A location from ?lat=&lng= (shareable links), else the browser's, on request.
export function useGeo() {
  const [state, setState] = useState(() => {
    const query = new URLSearchParams(window.location.search);
    const lat = Number(query.get('lat')), lng = Number(query.get('lng'));
    return query.has('lat') && query.has('lng') && Number.isFinite(lat) && Number.isFinite(lng)
      ? { status: 'ready', lat, lng } : { status: 'idle' };
  });
  const locate = useCallback(() => {
    if (!navigator.geolocation) {
      setState({ status: 'error', message: 'This browser has no location access.' });
      return;
    }
    setState((s) => ({ ...s, status: s.lat != null ? 'ready' : 'locating' }));
    navigator.geolocation.getCurrentPosition(
      ({ coords }) => setState({ status: 'ready', lat: Number(coords.latitude.toFixed(5)), lng: Number(coords.longitude.toFixed(5)) }),
      () => setState({ status: 'error', message: 'Allow location to find stations near you.' }),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 });
  }, []);
  return [state, locate];
}

// Fetch with `params`, then again every minute while the page is visible.
export function usePolling(path, params, enabled = true) {
  const [state, setState] = useState({ status: 'idle' });
  const key = JSON.stringify(params);
  const latest = useRef(0);
  useEffect(() => {
    if (!enabled) return undefined;
    let timer;
    const load = async () => {
      const call = ++latest.current;
      setState((s) => ({ ...s, status: s.data ? 'refreshing' : 'loading' }));
      try {
        const data = await getJson(path, JSON.parse(key));
        if (call === latest.current) setState({ status: 'ready', data, at: Date.now() });
      } catch (error) {
        if (call === latest.current) setState((s) => ({ ...s, status: 'error', message: error.message }));
      }
    };
    const tick = () => { if (document.visibilityState !== 'hidden') load(); };
    load();
    timer = setInterval(tick, REFRESH_MS);
    document.addEventListener('visibilitychange', tick);
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', tick); };
  }, [path, key, enabled]);
  return state;
}

export const percent = (p) => (p == null ? null : p >= 0.995 ? '>99%' : `${Math.round(p * 100)}%`);
export const mins = (m) => (m == null ? '—' : `${Math.max(1, Math.round(m))} min`);
