import React, { useState } from 'react';
import { X } from 'lucide-react';
import BikeMap from './BikeMap.jsx';
import Conditions from './Conditions.jsx';
import Freshness from './Freshness.jsx';
import LocateButton from './LocateButton.jsx';
import ModeSwitch from './Mode.jsx';
import PlaceSearch from './PlaceSearch.jsx';
import { mins, odds, usePolling } from './live.js';

// Some stations send report times near 1970, so long silences read as "over a day".
export function reportedLabel(s) {
  if (s == null) return null;
  if (s < 90) return 'Reported just now';
  if (s < 5400) return `Reported ${Math.round(s / 60)} min ago`;
  if (s < 172800) return `Reported ${Math.round(s / 3600)} hours ago`;
  return 'No report in over a day';
}
const plural = (n, word) => `${word}${n === 1 ? '' : 's'}`;

// The data behind the verdict, in one line: walk, what is there now, and the odds.
export function dataLine(station, need, fromStation) {
  const classic = station.bikes - station.ebikes;
  const counts = need === 'dock'
    ? [`${station.open_docks} ${plural(station.open_docks, 'dock')}`, `${station.bikes} ${plural(station.bikes, 'bike')}`]
    : [`${classic} classic`, `${station.ebikes} ${plural(station.ebikes, 'e-bike')}`, `${station.open_docks} ${plural(station.open_docks, 'dock')}`];
  const parts = [fromStation && station.walk_min < 0.5 ? 'Here' : `${mins(station.walk_min)} walk`, counts.join(', ')];
  if (station.docks_disabled > 0) parts.push(`${station.docks_disabled} broken`);
  if (station.chance != null && station.status === 'available' && station.chance < 0.95) parts.push(`${odds(station.chance)} it lasts`);
  if (station.chance != null && (station.status === 'empty' || station.status === 'full') && station.chance >= 0.05) {
    parts.push(`${odds(station.chance)} it refills in time`);
  }
  return parts.join(' · ');
}

function StationCard({ station, need, best, selected, fromStation, onPlan, onClose }) {
  const verdict = station.verdict ?? { tone: 'unknown', text: 'No live answer' };
  return (
    <li className={`cc-card bk-station${best ? ' is-best' : ''}${selected ? ' is-selected' : ''}`}>
      <div className="bk-station__head">
        <h3>{selected && <span className="bk-station__tag">Selected · </span>}{best && <span className="bk-station__tag">Best · </span>}{station.station}</h3>
        {onClose && (
          <button type="button" className="bk-from__clear" onClick={onClose} aria-label="Close selected station"><X size={16} aria-hidden="true" /></button>
        )}
      </div>
      <p className={`bk-verdict bk-verdict--${verdict.tone}`}>{verdict.text}</p>
      <p className="bk-data">{dataLine(station, need, fromStation)}</p>
      {station.reported_s != null && (
        <p className={`bk-station__age${station.status === 'unknown' ? ' is-stale' : ''}`}>{reportedLabel(station.reported_s)}</p>
      )}
      {selected && onPlan && (
        <div className="bk-pop__actions">
          <button type="button" className="cc-button cc-button--small cc-button--secondary"
            onClick={() => onPlan('from', { name: station.station, lat: station.lat, lng: station.lng })}>Plan from here</button>
          <button type="button" className="cc-button cc-button--small cc-button--secondary"
            onClick={() => onPlan('to', { name: station.station, lat: station.lat, lng: station.lng })}>Plan to here</button>
        </div>
      )}
    </li>
  );
}

// `origin` is where answers are from: { kind: 'you' | 'place' | 'pin' | 'station', name, lat, lng }.
export default function NearMe({ origin, you, geo, locate, onOrigin, need, setNeed, live, focus, onPlan }) {
  const [selected, setSelected] = useState(() => focus?.station ?? origin.station ?? null);
  const params = { lat: origin.lat, lng: origin.lng, need, limit: 5, include: selected };
  const wait = usePolling('wait', params, true);
  const result = wait.data;
  const pick = (place) => {
    onOrigin({ kind: place.station ? 'station' : 'place', name: place.name, lat: place.lat, lng: place.lng });
    setSelected(place.station ?? null);
  };
  const fromStation = origin.kind === 'station';
  // The selected card leads; it is left out of the list below when it is also one of the nearest.
  const shown = result?.selected && result.selected.station_id === selected ? result.selected : null;
  const nearest = result ? result.stations.filter((s) => s.station_id !== shown?.station_id) : [];
  return (
    <section className="bk-pane" aria-label="Near me">
      <div className="bk-near-head">
        <ModeSwitch need={need} setNeed={setNeed} />
        <LocateButton geo={geo} locate={locate} compact />
      </div>
      <PlaceSearch stations={live.data?.stations} origin={origin} onPick={pick}
        onClear={you ? () => { onOrigin(null); setSelected(null); } : null} />
      {wait.status === 'error' && !result && <p className="cc-notice cc-notice--error" role="alert">{wait.message}</p>}
      {!result && wait.status === 'loading' && <p className="cc-caption">Checking stations…</p>}
      {result && (
        <div className={`bk-results${wait.status === 'error' ? ' is-stale' : ''}`}>
          <Freshness state={wait} />
          <Conditions conditions={result.conditions} />
          <p className="bk-answer-line" aria-live="polite">{result.answer ?? result.message}</p>
          {live.data && (
            <BikeMap stations={live.data.stations} home={origin} you={you} focus={focus} need={need}
              highlight={result.stations.map((s) => s.station_id)} selected={selected} onSelect={setSelected}
              onPin={(p) => { onOrigin({ kind: 'pin', name: 'Dropped pin', ...p }); setSelected(null); }} />
          )}
          <ol className="bk-stations">
            {shown && (
              <StationCard station={shown} need={need} selected fromStation={fromStation}
                best={result.best?.station_id === shown.station_id} onPlan={onPlan} onClose={() => setSelected(null)} />
            )}
            {nearest.map((s) => (
              <StationCard key={s.station_id} station={s} need={need} fromStation={fromStation}
                best={result.best?.station_id === s.station_id} />
            ))}
          </ol>
          <p className="cc-caption bk-source">Odds use a year of Citi Bike trips. Map and places © OpenStreetMap contributors.</p>
        </div>
      )}
    </section>
  );
}
