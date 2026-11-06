import React, { useEffect, useMemo, useState } from 'react';
import { MapPin, Search, X } from 'lucide-react';
import { getJson } from './live.js';

// Same folding as the API's /bikes/stations search: "west 31st street" finds "W 31 St".
const WORDS = { street: 'st', avenue: 'ave', av: 'ave', east: 'e', west: 'w', north: 'n', south: 's',
  place: 'pl', boulevard: 'blvd', road: 'rd', square: 'sq', and: '&' };
export const searchWords = (text) => (text.toLowerCase().match(/[a-z0-9&]+/g) || [])
  .map((w) => WORDS[w] ?? w.replace(/^(\d+)(st|nd|rd|th)$/, '$1'));
export function matches(name, words) {
  const tokens = searchWords(name);
  return words.every((w) => (/^\d+$/.test(w) ? tokens.includes(w) : tokens.some((t) => t.startsWith(w))));
}

// Stations from the live feed first (they are what you came for), then addresses
// and places from /bikes/places, which is built into our API from OpenStreetMap.
export function usePlaceResults(text, stations, near = null) {
  const [places, setPlaces] = useState([]);
  const trimmed = text.trim();
  useEffect(() => {
    if (trimmed.length < 2) { setPlaces([]); return undefined; }
    let live = true;
    const timer = setTimeout(() => {
      getJson('places', { q: trimmed, limit: 6, lat: near?.lat, lng: near?.lng }).then((body) => { if (live) setPlaces(body.places); }, () => {});
    }, 180);
    return () => { live = false; clearTimeout(timer); };
  }, [trimmed, near?.lat, near?.lng]);
  const found = useMemo(() => {
    const words = searchWords(trimmed);
    if (!words.length || !stations) return [];
    return stations.name.map((name, i) => [name, i]).filter(([name]) => matches(name, words)).slice(0, 3)
      .map(([name, i]) => ({ name, lat: stations.lat[i], lng: stations.lng[i], station: stations.id[i], detail: 'Station' }));
  }, [trimmed, stations]);
  return [...found, ...places.map((p) => ({ name: p.label, lat: p.lat, lng: p.lng, detail: p.area || null }))];
}

// "From" for Near me: you, a searched address or place, a station, or a dropped pin.
export default function PlaceSearch({ stations, origin, near = origin, onPick, onClear }) {
  const [text, setText] = useState('');
  const [open, setOpen] = useState(false);
  const results = usePlaceResults(text, stations, near);
  const pick = (place) => { onPick(place); setText(''); setOpen(false); };
  if (!open && origin && origin.kind !== 'you') {
    return (
      <div className="bk-from">
        <MapPin size={18} aria-hidden="true" />
        <span className="bk-from__label">From <b>{origin.name}</b></span>
        <button type="button" className="bk-link" onClick={() => setOpen(true)}>Change</button>
        {onClear && (
          <button type="button" className="bk-from__clear" onClick={onClear} aria-label="Back to my location">
            <X size={16} aria-hidden="true" />
          </button>
        )}
      </div>
    );
  }
  return (
    <div className="bk-search bk-from-search">
      <div className="bk-from-search__box">
        <Search size={18} aria-hidden="true" />
        <input className="cc-input" type="search" autoComplete="off" aria-label="Search an address, place or station"
          placeholder="Address, place or station" value={text} autoFocus={open}
          onChange={(e) => setText(e.target.value)} onKeyDown={(e) => { if (e.key === 'Escape') setOpen(false); }} />
      </div>
      <ul className="bk-search__results">
        {results.map((r) => (
          <li key={`${r.station ?? ''}${r.name}${r.lat}`}>
            <button type="button" onClick={() => pick(r)}>
              <span>{r.name}</span>{r.detail && <small>{r.detail}</small>}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}
