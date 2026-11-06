import React from 'react';
import LocalMap from './LocalMap.jsx';
import Freshness from './Freshness.jsx';
import LocateButton from './LocateButton.jsx';
import { mins, percent, usePolling } from './live.js';

export const NEEDS = [
  { key: 'bike', label: 'Bike' },
  { key: 'ebike', label: 'E-bike' },
  { key: 'dock', label: 'Dock' },
];
const STATUS = { available: 'Available', empty: 'Empty', full: 'Full', closed: 'Closed', unknown: 'No recent report' };

// Some stations send report times near 1970, so long silences read as "over a day".
export function reportedLabel(s) {
  if (s == null) return null;
  if (s < 90) return 'Reported just now';
  if (s < 5400) return `Reported ${Math.round(s / 60)} min ago`;
  if (s < 172800) return `Reported ${Math.round(s / 3600)} hours ago`;
  return 'No report in over a day';
}
const plural = (n, word) => `${word}${n === 1 ? '' : 's'}`;

function Counts({ station }) {
  return (
    <span className="bk-counts">
      <span><b>{station.bikes - station.ebikes}</b> classic</span>
      <span><b>{station.ebikes}</b> {plural(station.ebikes, 'e-bike')}</span>
      <span><b>{station.open_docks}</b> {plural(station.open_docks, 'dock')}</span>
      {station.docks_disabled > 0 && <span><b>{station.docks_disabled}</b> broken</span>}
    </span>
  );
}

function StationCard({ station, best }) {
  const missing = station.status === 'empty' || station.status === 'full';
  return (
    <li className={`cc-card bk-station${best ? ' is-best' : ''}`}>
      <div className="bk-station__head">
        <h3>{station.station}</h3>
        <span className={`bk-pill bk-pill--${station.status}`}>{best ? 'Best · ' : ''}{STATUS[station.status]}</span>
      </div>
      <Counts station={station} />
      <dl className="bk-station__facts">
        <div><dt>Walk</dt><dd>{mins(station.walk_min)}</dd></div>
        <div><dt>{missing ? 'Back by arrival' : 'Still there'}</dt><dd>{percent(station.chance) ?? '—'}</dd></div>
        <div><dt>If gone, wait</dt><dd>{station.wait_min == null ? 'rare' : mins(station.wait_min)}</dd></div>
        <div><dt>Expected</dt><dd>{mins(station.expected_min)}</dd></div>
      </dl>
      {station.reported_s != null && (
        <p className={`bk-station__age${station.status === 'unknown' ? ' is-stale' : ''}`}>{reportedLabel(station.reported_s)}</p>
      )}
    </li>
  );
}

export default function NearMe({ geo, locate, need, setNeed, live }) {
  const params = geo.status === 'ready' ? { lat: geo.lat, lng: geo.lng, need, limit: 5 } : null;
  const wait = usePolling('wait', params, Boolean(params));
  const result = wait.data;
  return (
    <section className="bk-pane" aria-label="Near me">
      <div className="bk-near-head">
        <div className="cc-segmented bk-needs" role="tablist" aria-label="I need">
          {NEEDS.map((n) => (
            <button key={n.key} type="button" role="tab" className="cc-segmented__item"
              aria-selected={need === n.key} onClick={() => setNeed(n.key)}>{n.label}</button>
          ))}
        </div>
        <LocateButton geo={geo} locate={locate} compact />
      </div>
      {wait.status === 'error' && !result && <p className="cc-notice cc-notice--error" role="alert">{wait.message}</p>}
      {!result && wait.status === 'loading' && <p className="cc-caption">Checking stations…</p>}
      {result && (
        <div className={`bk-results${wait.status === 'error' ? ' is-stale' : ''}`}>
          <Freshness state={wait} />
          <p className="bk-answer-line" aria-live="polite">{result.message}</p>
          {live.data && (
            <LocalMap stations={live.data.stations} center={geo} need={need}
              highlight={result.stations.map((s) => s.station_id)} />
          )}
          <ol className="bk-stations">
            {result.stations.map((s) => (
              <StationCard key={s.station_id} station={s} best={result.best?.station_id === s.station_id} />
            ))}
          </ol>
          <p className="cc-caption bk-source">Odds use a year of Citi Bike trips.</p>
        </div>
      )}
    </section>
  );
}
