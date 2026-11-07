import React, { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import BikeMap, { LEVELS } from './BikeMap.jsx';
import Conditions from './Conditions.jsx';
import Freshness from './Freshness.jsx';
import LocateButton from './LocateButton.jsx';
import ModeSwitch from './Mode.jsx';
import PlaceSearch from './PlaceSearch.jsx';
import StationSheet from './StationSheet.jsx';
import { mins, odds, reportedLabel, usePolling } from './live.js';

export { reportedLabel };

// Midtown, for a first look before you locate or search.
const MIDTOWN = { lat: 40.7505, lng: -73.9894 };
// What covers the map, for fitting routes into the rest: on a phone, search and
// the bike or dock keys on top and the lowered sheet (42% of the height) below; on
// a wide screen, the 400 px column on the left holding all three.
const wide = () => typeof window !== 'undefined' && window.matchMedia?.('(min-width: 760px)').matches;
const insets = () => (wide() ? { top: 16, left: 432 } : { top: 128, bottom: 0.42 });
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

// A nearby station as one tappable row: its verdict, the data behind it, and minutes until you have one.
function StationRow({ station, need, best, fromStation, onSelect }) {
  const verdict = station.verdict ?? { tone: 'unknown', text: 'No live answer' };
  return (
    <li className={`bk-option bk-station${best ? ' is-best' : ''}`}>
      <i className={`bk-option__dot bk-verdict--${verdict.tone}`} aria-hidden="true" />
      <button type="button" className="bk-option__body" onClick={() => onSelect(station.station_id)}>
        <b>{best && <span className="bk-station__tag">Best · </span>}{station.station}</b>
        <span className={`bk-verdict--${verdict.tone}`}>{verdict.text}</span>
        <span>{dataLine(station, need, fromStation)}</span>
        {station.status === 'unknown' && station.reported_s != null && (
          <span className="bk-station__age is-stale">{reportedLabel(station.reported_s)}</span>
        )}
      </button>
      <span className="bk-option__total">{station.expected_min == null ? '—' : mins(station.expected_min)}</span>
    </li>
  );
}

function Legend({ need }) {
  const noun = need === 'dock' ? 'open docks' : need === 'ebike' ? 'e-bikes' : 'bikes';
  return (
    <ul className="bk-legend bk-legend--ramp" aria-label={`Map colors: ${noun}`}>
      {LEVELS.filter((l) => l.key !== 'unknown').map((l) => (
        <li key={l.key}><i style={{ background: l.color }} />{l.key === 'closed' ? l.label : `${l.label} ${noun}`}</li>
      ))}
    </ul>
  );
}

// Routes for the map: from a station to its options, or from where you are to the nearest stations.
function stationRoutes(result, need) {
  const here = result.station;
  return {
    from: here,
    to: result.options.map((o) => ({
      id: o.station_id, lat: o.lat, lng: o.lng, tone: o.verdict?.tone, ride: need === 'dock',
      best: o.station_id === result.best?.station_id,
      label: o.station_id !== here.station_id ? mins(o.expected_min)
        : o.status === 'available' ? 'Here' : `Wait ${mins(o.expected_min ?? o.wait_min)}`,
    })),
  };
}

function nearbyRoutes(result, origin) {
  return {
    from: origin,
    to: result.stations.map((s) => ({
      id: s.station_id, lat: s.lat, lng: s.lng, tone: s.verdict?.tone, best: s.station_id === result.best?.station_id,
      label: mins(s.expected_min ?? s.walk_min),
    })),
  };
}

// Near me, map first: the map fills the screen; search and the bike or dock choice
// float on it; a sheet at the bottom gives the call. Tap a station to stand there.
// `origin` is where answers are from ({ kind: 'you' | 'place' | 'pin' | 'station',
// name, lat, lng }), or null before you locate or search.
export default function NearMe({ origin, you, geo, locate, onOrigin, need, setNeed, live, focus, onPlan }) {
  const [selected, setSelected] = useState(() => focus?.station ?? origin?.station ?? null);
  const [full, setFull] = useState(false);
  const wait = usePolling('wait', origin ? { lat: origin.lat, lng: origin.lng, need, limit: 5 } : null, Boolean(origin));
  const options = usePolling('options', { station: selected, need }, Boolean(selected));
  const result = origin ? wait.data : null;
  const atStation = selected && options.data?.station?.station_id === selected ? options.data : null;
  const pick = (place) => {
    onOrigin({ kind: place.station ? 'station' : 'place', name: place.name, lat: place.lat, lng: place.lng });
    setSelected(place.station ?? null);
  };
  const select = (id) => { setSelected(id); setFull(false); };
  const routes = atStation ? stationRoutes(atStation, need) : result && !selected ? nearbyRoutes(result, origin) : null;
  const fit = atStation
    ? { key: `at:${selected}:${need}`, points: [atStation.station, ...atStation.options] }
    : result && !selected ? { key: `near:${origin.lat},${origin.lng}:${need}`, points: [origin, ...result.stations] } : null;
  return (
    <section className="bk-mapview" aria-label="Near me">
      {live.data ? (
        <BikeMap stations={live.data.stations} home={origin} you={you} center={MIDTOWN} focus={focus} need={need}
          highlight={result ? result.stations.map((s) => s.station_id) : []} selected={selected} onSelect={select}
          routes={routes} fit={fit} inset={insets()}
          onPin={(p) => { onOrigin({ kind: 'pin', name: 'Dropped pin', ...p }); setSelected(null); }} />
      ) : (
        <p className="cc-caption bk-mapview__loading">{live.status === 'error' ? live.message : 'Loading stations…'}</p>
      )}
      <div className="bk-float">
        <PlaceSearch stations={live.data?.stations} origin={origin} onPick={pick}
          onClear={you && origin?.kind !== 'you' ? () => { onOrigin(null); setSelected(null); } : null} />
        <div className="bk-float__row">
          <ModeSwitch need={need} setNeed={setNeed} />
          <LocateButton geo={geo} locate={locate} compact />
        </div>
      </div>
      <div className={`bk-sheet2${full ? ' is-full' : ''}`}>
        <button type="button" className="bk-sheet2__handle" onClick={() => setFull((f) => !f)}
          aria-label={full ? 'Lower the panel' : 'Raise the panel'} aria-expanded={full}>
          {full ? <ChevronDown size={18} aria-hidden="true" /> : <ChevronUp size={18} aria-hidden="true" />}
        </button>
        {selected ? (
          atStation ? (
            <StationSheet result={atStation} need={need} onClose={() => setSelected(null)} onPlan={onPlan}
              onStartHere={(place) => { onOrigin({ kind: 'station', ...place }); setSelected(null); }} />
          ) : options.status === 'error' ? (
            <p className="cc-notice cc-notice--error" role="alert">{options.message}</p>
          ) : <p className="cc-caption">Checking the station…</p>
        ) : !origin ? (
          <div className="bk-sheet2__intro">
            <p className="bk-verdict">Where are you starting?</p>
            <p className="bk-data">{geo.status === 'locating' ? 'Finding you…' : 'Locate yourself, search above, or tap a station on the map.'}</p>
            {geo.status === 'error' && <p className="cc-notice cc-notice--error" role="alert">{geo.message}</p>}
            <LocateButton geo={geo} locate={locate} label="Use my location" variant="primary" />
          </div>
        ) : (
          <>
            {wait.status === 'error' && !result && <p className="cc-notice cc-notice--error" role="alert">{wait.message}</p>}
            {!result && wait.status === 'loading' && <p className="cc-caption">Checking stations…</p>}
            {result && (
              <div className={`bk-results${wait.status === 'error' ? ' is-stale' : ''}`}>
                <p className="bk-answer-line" aria-live="polite">{result.answer ?? result.message}</p>
                <Conditions conditions={result.conditions} />
                <ol className="bk-options">
                  {result.stations.map((s) => (
                    <StationRow key={s.station_id} station={s} need={need} fromStation={origin.kind === 'station'}
                      best={result.best?.station_id === s.station_id} onSelect={select} />
                  ))}
                </ol>
                <Freshness state={wait} />
              </div>
            )}
          </>
        )}
        <Legend need={need} />
        <p className="cc-caption bk-source">Odds use a year of Citi Bike trips. Map and places © OpenStreetMap contributors.</p>
      </div>
    </section>
  );
}
