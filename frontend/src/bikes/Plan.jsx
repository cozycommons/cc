import React, { useMemo, useState } from 'react';
import { mins, percent, usePolling } from './live.js';

const LEAVE = [{ label: 'Now', minutes: 0 }, { label: '15 min', minutes: 15 }, { label: '30 min', minutes: 30 }, { label: '1 hr', minutes: 60 }];

function StationSearch({ id, label, stations, value, onPick, mine }) {
  const [text, setText] = useState('');
  const matches = useMemo(() => {
    const words = text.toLowerCase().split(/\s+/).filter(Boolean);
    if (!words.length || !stations) return [];
    return stations.name.map((name, i) => [name, i])
      .filter(([name]) => words.every((w) => name.toLowerCase().includes(w))).slice(0, 6);
  }, [text, stations]);
  return (
    <div className="bk-search">
      <label className="cc-label" htmlFor={id}>{label}</label>
      {value ? (
        <div className="bk-search__picked">
          <span>{value.name}</span>
          <button type="button" className="bk-link" onClick={() => { onPick(null); setText(''); }}>Change</button>
        </div>
      ) : (
        <>
          <input id={id} className="cc-input" type="search" placeholder="Station or street" autoComplete="off"
            value={text} onChange={(e) => setText(e.target.value)} />
          <ul className="bk-search__results">
            {mine && !text && <li><button type="button" onClick={() => onPick(mine)}>My location</button></li>}
            {matches.map(([name, i]) => (
              <li key={stations.id[i]}>
                <button type="button" onClick={() => onPick({ name, lat: stations.lat[i], lng: stations.lng[i] })}>{name}</button>
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
      <span>{count} {what} now{station.chance != null ? ` · ${percent(station.chance)} likely on arrival` : ''}</span>
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

export default function Plan({ geo, locate, live }) {
  const mine = geo.status === 'ready' ? { name: 'My location', lat: geo.lat, lng: geo.lng } : null;
  const [from, setFrom] = useState(null);
  const [to, setTo] = useState(null);
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
      {!mine && geo.status !== 'locating' && (
        <button type="button" className="cc-button cc-button--secondary" onClick={locate}>Start from my location</button>
      )}
      <StationSearch id="bk-from" label="From" stations={stations} value={from ?? mine}
        onPick={(v) => setFrom(v && v.name === 'My location' ? null : v)} mine={mine} />
      <StationSearch id="bk-to" label="To" stations={stations} value={to} onPick={setTo} />
      <div className="bk-row">
        <div className="cc-segmented" role="tablist" aria-label="Leave">
          {LEAVE.map((l) => (
            <button key={l.label} type="button" role="tab" className="cc-segmented__item"
              aria-selected={leave === l.minutes} onClick={() => setLeave(l.minutes)}>{l.label}</button>
          ))}
        </div>
        <label className="bk-check"><input type="checkbox" checked={ebike} onChange={(e) => setEbike(e.target.checked)} /> E-bike</label>
      </div>
      {plan.status === 'error' && <p className="cc-notice cc-notice--error" role="alert">{plan.message}</p>}
      {result?.best && (
        <article className="cc-card bk-plan" aria-live="polite">
          <p className="bk-plan__total"><b>{mins(result.best.expected_min)}</b> by bike · {mins(result.walk_only_min)} walking</p>
          <p className="cc-body">{result.message}</p>
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
      {result && !result.best && <p className="cc-body">{result.message}</p>}
    </section>
  );
}
