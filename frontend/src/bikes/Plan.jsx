import React, { useState } from 'react';
import Conditions from './Conditions.jsx';
import Freshness from './Freshness.jsx';
import LocateButton from './LocateButton.jsx';
import { mins, odds, usePolling } from './live.js';
import { usePlaceResults } from './PlaceSearch.jsx';

const LEAVE = [{ label: 'Now', minutes: 0 }, { label: '15 min', minutes: 15 }, { label: '30 min', minutes: 30 }, { label: '1 hr', minutes: 60 }];

function StationSearch({ id, label, stations, value, onPick, mine, action, near }) {
  const [text, setText] = useState('');
  const found = usePlaceResults(text, stations, near);
  return (
    <div className="bk-search">
      <label className="cc-label" htmlFor={id}>{label}</label>
      {value ? (
        <div className="bk-search__picked">
          <span>{value.name}</span>
          <span className="bk-search__actions">
            {action}
            <button type="button" className="bk-link" onClick={() => { onPick(null); setText(''); }}>Change</button>
          </span>
        </div>
      ) : (
        <>
          <input id={id} className="cc-input" type="search" placeholder="Address, place or station" autoComplete="off"
            value={text} onChange={(e) => setText(e.target.value)} />
          <ul className="bk-search__results">
            {mine && !text && <li><button type="button" onClick={() => onPick(mine)}>My location</button></li>}
            {found.map((r) => (
              <li key={`${r.station ?? ''}${r.name}${r.lat}`}>
                <button type="button" onClick={() => onPick({ name: r.name, lat: r.lat, lng: r.lng })}>
                  <span>{r.name}</span>{r.detail && <small>{r.detail}</small>}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function Leg({ kind, station, noun }) {
  const count = noun === 'dock' ? station.open_docks : noun === 'ebike' ? station.ebikes : station.bikes;
  const what = noun === 'dock' ? 'docks' : noun === 'ebike' ? 'e-bikes' : 'bikes';
  return (
    <li className={`bk-step bk-step--${kind}`}>
      <b>{station.station}</b>
      <span>{count} {what} now{station.chance != null ? ` · odds on arrival ${odds(station.chance)}` : ''}</span>
    </li>
  );
}

function Route({ option, ebike }) {
  return (
    <ol className="bk-steps">
      <li className="bk-step bk-step--walk">Walk {mins(option.start.walk_min)}</li>
      <Leg kind="start" station={option.start} noun={ebike ? 'ebike' : 'bike'} />
      <li className="bk-step bk-step--ride">Ride {mins(option.ride_min)}</li>
      <Leg kind="end" station={option.end} noun="dock" />
      <li className="bk-step bk-step--walk">Walk {mins(option.end.walk_min)}</li>
    </ol>
  );
}

export default function Plan({ geo, locate, live, seed }) {
  const mine = geo.status === 'ready' ? { name: 'My location', lat: geo.lat, lng: geo.lng } : null;
  // `seed` carries a station picked on the map ("Plan from here" / "Plan to here").
  const [from, setFrom] = useState(() => seed?.from ?? null);
  const [to, setTo] = useState(() => seed?.to ?? null);
  const [leave, setLeave] = useState(0);
  const [ebike, setEbike] = useState(false);
  const origin = from ?? mine;
  const depart = leave ? new Date(Date.now() + leave * 60000).toISOString().slice(0, 16) + 'Z' : null;
  const params = origin && to ? {
    from_lat: origin.lat, from_lng: origin.lng, to_lat: to.lat, to_lng: to.lng,
    ebike: ebike ? 'true' : null, depart,
  } : null;
  const plan = usePolling('plan', params, Boolean(params));
  const stations = live.data?.stations;
  const result = plan.data;
  return (
    <section className="bk-pane" aria-label="Plan a trip">
      {!mine && <LocateButton geo={geo} locate={locate} label="Use my location" />}
      {geo.status === 'error' && <p className="cc-notice cc-notice--error" role="alert">{geo.message}</p>}
      <StationSearch id="bk-from" label="From" stations={stations} value={from ?? mine}
        onPick={(v) => setFrom(v && v.name === 'My location' ? null : v)} mine={mine}
        action={!from && mine ? <LocateButton geo={geo} locate={locate} compact /> : null} near={mine} />
      <StationSearch id="bk-to" label="To" stations={stations} value={to} onPick={setTo} near={origin} />
      <div className="bk-row">
        <div className="cc-segmented" role="tablist" aria-label="Leave">
          {LEAVE.map((l) => (
            <button key={l.label} type="button" role="tab" className="cc-segmented__item"
              aria-selected={leave === l.minutes} onClick={() => setLeave(l.minutes)}>{l.label}</button>
          ))}
        </div>
        <label className="bk-check"><input type="checkbox" checked={ebike} onChange={(e) => setEbike(e.target.checked)} /> E-bike</label>
      </div>
      {plan.status === 'error' && !result && <p className="cc-notice cc-notice--error" role="alert">{plan.message}</p>}
      {result?.live && <Freshness state={plan} />}
      {result && <Conditions conditions={result.conditions} />}
      {result?.best && (
        <article className={`cc-card bk-plan${plan.status === 'error' ? ' is-stale' : ''}`} aria-live="polite">
          <p className="bk-plan__total"><b>{mins(result.best.expected_min)}</b> by bike · {mins(result.walk_only_min)} walking</p>
          <p className="cc-body">{result.answer ?? result.message}</p>
          <Route option={result.best} ebike={ebike} />
          {!result.live && <p className="cc-caption">More than an hour out: timing only, no live odds.</p>}
          {result.alternatives.length > 0 && (
            <details className="bk-alts">
              <summary>Other stations</summary>
              <ul>
                {result.alternatives.map((o) => (
                  <li key={`${o.start.station_id}-${o.end.station_id}`}>
                    {o.start.station} → {o.end.station}: {mins(o.expected_min)}
                  </li>
                ))}
              </ul>
            </details>
          )}
        </article>
      )}
      {result && !result.best && <p className="cc-body">{result.answer ?? result.message}</p>}
    </section>
  );
}
