import React, { useState } from 'react';
import { X } from 'lucide-react';
import BikeMap from './BikeMap.jsx';
import Conditions from './Conditions.jsx';
import Freshness from './Freshness.jsx';
import LocateButton from './LocateButton.jsx';
import ModeSwitch from './Mode.jsx';
import PlaceSearch from './PlaceSearch.jsx';
import StationSheet from './StationSheet.jsx';
import { mins, odds, reportedLabel, usePolling } from './live.js';

export { reportedLabel };

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

function StationCard({ station, need, best, fromStation }) {
  const verdict = station.verdict ?? { tone: 'unknown', text: 'No live answer' };
  return (
    <li className={`cc-card bk-station${best ? ' is-best' : ''}`}>
      <div className="bk-station__head">
        <h3>{best && <span className="bk-station__tag">Best · </span>}{station.station}</h3>
      </div>
      <p className={`bk-verdict bk-verdict--${verdict.tone}`}>{verdict.text}</p>
      <p className="bk-data">{dataLine(station, need, fromStation)}</p>
      {station.reported_s != null && (
        <p className={`bk-station__age${station.status === 'unknown' ? ' is-stale' : ''}`}>{reportedLabel(station.reported_s)}</p>
      )}
    </li>
  );
}

// `origin` is where answers are from: { kind: 'you' | 'place' | 'pin' | 'station', name, lat, lng }.
export default function NearMe({ origin, you, geo, locate, onOrigin, need, setNeed, live, focus, onPlan }) {
  const [selected, setSelected] = useState(() => focus?.station ?? origin.station ?? null);
  const params = { lat: origin.lat, lng: origin.lng, need, limit: 5 };
  const wait = usePolling('wait', params, true);
  const result = wait.data;
  const pick = (place) => {
    onOrigin({ kind: place.station ? 'station' : 'place', name: place.name, lat: place.lat, lng: place.lng });
    setSelected(place.station ?? null);
  };
  const fromStation = origin.kind === 'station';
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
            {result.stations.map((s) => (
              <StationCard key={s.station_id} station={s} need={need} fromStation={fromStation}
                best={result.best?.station_id === s.station_id} />
            ))}
          </ol>
          <p className="cc-caption bk-source">Odds use a year of Citi Bike trips. Map and places © OpenStreetMap contributors.</p>
        </div>
      )}
      {selected && (
        <StationSheet stationId={selected} need={need} onClose={() => setSelected(null)} onPlan={onPlan}
          onStartHere={(place) => { onOrigin({ kind: 'station', ...place }); setSelected(null); }} />
      )}
    </section>
  );
}
