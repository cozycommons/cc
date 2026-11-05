import React, { useEffect, useMemo, useRef, useState } from 'react';
import LineChart from './LineChart.jsx';

// Ordinal blue steps 250-700, validated against the card surface; bins are departures per hour.
const RAMP = ['#86b6ef', '#5598e7', '#2a78d6', '#1c5cab', '#0d366b'];
const BINS = [1, 3, 8, 20];
const BIN_LABELS = ['< 1', '1–3', '3–8', '8–20', '20+'];
const WEEKDAY = '#2a78d6';
const WEEKEND = '#eb6834';
const MAP_W = 600;

export const hourLabel = (h) => `${h % 12 || 12} ${h < 12 ? 'AM' : 'PM'}`;
const perHour = (rates, weekend, hour) => rates[24 * weekend + hour] / 100;
const bin = (rate) => BINS.filter((b) => rate >= b).length;
const waitLabel = (rate) => {
  if (rate <= 0) return 'no departures';
  return rate > 60 ? `${Math.round(3600 / rate)} s` : `${Math.round(60 / rate)} min`;
};
const compact = (v) => (v >= 1e6 ? `${(v / 1e6).toFixed(v % 1e6 ? 1 : 0)}M` : v >= 1e3 ? `${Math.round(v / 1e3)}k` : `${v}`);

function project({ lat, lng }) {
  const k = Math.cos(((Math.min(...lat) + Math.max(...lat)) / 2) * Math.PI / 180);
  const x0 = Math.min(...lng) * k, x1 = Math.max(...lng) * k;
  const y0 = Math.min(...lat), y1 = Math.max(...lat);
  const scale = (MAP_W - 16) / (x1 - x0);
  return {
    height: Math.round((y1 - y0) * scale + 16),
    points: lat.map((la, i) => [8 + (lng[i] * k - x0) * scale, 8 + (y1 - la) * scale]),
  };
}

function StationMap({ stations, map, hour, weekend, selected, onSelect }) {
  const svg = useRef(null);
  const [hover, setHover] = useState(null);
  const nearest = (event) => {
    const box = svg.current.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * MAP_W;
    const py = ((event.clientY - box.top) / box.height) * map.height;
    let best = null, bestD = 144; // within 12 map units
    map.points.forEach(([x, y], i) => {
      const d = (x - px) ** 2 + (y - py) ** 2;
      if (d < bestD) { best = i; bestD = d; }
    });
    return best;
  };
  const shown = hover ?? selected;
  return (
    <div className="bk-map">
      <svg ref={svg} viewBox={`0 0 ${MAP_W} ${map.height}`} role="img"
        aria-label={`Citi Bike stations colored by departures per hour at ${hourLabel(hour)}`}
        onPointerMove={(e) => setHover(nearest(e))} onPointerLeave={() => setHover(null)}
        onClick={(e) => { const i = nearest(e); if (i != null) onSelect(i); }}>
        {map.points.map(([x, y], i) => (
          <circle key={stations.id[i]} cx={x} cy={y} r="2.6"
            fill={RAMP[bin(perHour(stations.rates[i], weekend, hour))]} />
        ))}
        {shown != null && (
          <circle className="bk-map__ring" cx={map.points[shown][0]} cy={map.points[shown][1]} r="6" />
        )}
      </svg>
      {hover != null && (
        <div className="bk-tooltip" style={{ left: `${(map.points[hover][0] / MAP_W) * 100}%`,
          top: `${(map.points[hover][1] / map.height) * 100}%` }}>
          <b className="bk-tooltip__title">{stations.name[hover]}</b>
          <span><strong>{perHour(stations.rates[hover], weekend, hour).toFixed(1)}</strong> departures / hr</span>
          <span><strong>{waitLabel(perHour(stations.rates[hover], weekend, hour))}</strong> usual wait when full</span>
        </div>
      )}
      <ul className="bk-legend bk-legend--ramp" aria-label="Departures per hour">
        {RAMP.map((color, i) => <li key={color}><i style={{ background: color }} />{BIN_LABELS[i]}</li>)}
      </ul>
    </div>
  );
}

function StationDetail({ stations, index, hour, weekend }) {
  const rates = stations.rates[index];
  const hours = Array.from({ length: 24 }, (_, h) => h);
  return (
    <section className="cc-card bk-panel" aria-live="polite">
      <h3 className="cc-h3">{stations.name[index]}</h3>
      <p className="cc-body">
        Full at {hourLabel(hour)} on a {weekend ? 'weekend' : 'weekday'}: a dock usually opens
        in {waitLabel(perHour(rates, weekend, hour))}.
      </p>
      <LineChart label={`Departures per hour at ${stations.name[index]}, weekday and weekend`}
        series={[
          { key: 'weekday', label: 'Weekday', color: WEEKDAY, values: hours.map((h) => perHour(rates, 0, h)) },
          { key: 'weekend', label: 'Weekend', color: WEEKEND, values: hours.map((h) => perHour(rates, 1, h)) },
        ]}
        xLabels={hours.map(hourLabel)} xTicks={[0, 6, 12, 18, 23]}
        formatY={(v, exact) => (exact ? v.toFixed(1) : `${v}`)} height={180} />
    </section>
  );
}

function Busiest({ stations, hour, weekend, onSelect }) {
  const top = stations.rates.map((r, i) => [perHour(r, weekend, hour), i]).sort((a, b) => b[0] - a[0]).slice(0, 8);
  return (
    <table className="bk-table">
      <caption>Busiest docks at {hourLabel(hour)}</caption>
      <thead><tr><th scope="col">Dock</th><th scope="col">Departures / hr</th><th scope="col">Usual wait</th></tr></thead>
      <tbody>
        {top.map(([rate, i]) => (
          <tr key={stations.id[i]}>
            <td><button type="button" className="bk-link" onClick={() => onSelect(i)}>{stations.name[i]}</button></td>
            <td>{rate.toFixed(1)}</td>
            <td>{waitLabel(rate)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}

function History({ history }) {
  const total = history.month.map((_, i) => history.nyc[i] + history.jc[i]);
  const years = history.month.map((m, i) => [m, i]).filter(([m]) => m.endsWith('-01')).map(([, i]) => i);
  const ticks = years.filter((_, k) => k % 2 === 0);
  return (
    <section className="bk-section">
      <h2 className="cc-h2">Trips per month</h2>
      <p className="cc-body">{compact(total.reduce((a, b) => a + b, 0))} trips since {history.month[0]}.</p>
      <LineChart label="Citi Bike trips per month" xLabels={history.month} tickLabel={(m) => m.slice(0, 4)}
        xTicks={ticks.length ? ticks : [0]} formatY={(v, exact) => (exact ? v.toLocaleString('en-US') : compact(v))}
        series={[{ key: 'trips', label: 'Trips', color: WEEKDAY, values: total }]} />
    </section>
  );
}

export default function Explore() {
  const [data, setData] = useState(null);
  const [failed, setFailed] = useState(false);
  const [hour, setHour] = useState(() => new Date().getHours());
  const [weekend, setWeekend] = useState(() => [0, 6].includes(new Date().getDay()) ? 1 : 0);
  const [selected, setSelected] = useState(null);
  useEffect(() => {
    let live = true;
    fetch('/bikes/explore.json').then((r) => (r.ok ? r.json() : Promise.reject(new Error(r.status))))
      .then((body) => { if (live) setData(body); }, () => { if (live) setFailed(true); });
    return () => { live = false; };
  }, []);
  const map = useMemo(() => (data ? project(data.stations) : null), [data]);
  if (failed) return <p className="cc-notice cc-notice--error" role="status">Could not load trip history.</p>;
  if (!data) return <p className="cc-caption">Loading trip history…</p>;
  const { stations } = data;
  return (
    <>
      <section className="bk-section">
        <h2 className="cc-h2">Every dock, by hour</h2>
        <p className="cc-caption">Mean departures per hour, {data.window[0]} to {data.window[1]}.</p>
        <div className="bk-controls">
          <div className="cc-segmented" role="tablist" aria-label="Day type">
            {['Weekday', 'Weekend'].map((name, i) => (
              <button key={name} type="button" role="tab" className="cc-segmented__item"
                aria-selected={weekend === i} onClick={() => setWeekend(i)}>{name}</button>
            ))}
          </div>
          <label className="bk-hour">
            <span>{hourLabel(hour)}</span>
            <input className="cc-range" type="range" min="0" max="23" value={hour}
              onChange={(e) => setHour(Number(e.target.value))} aria-label="Hour of day" />
          </label>
        </div>
        <StationMap stations={stations} map={map} hour={hour} weekend={weekend}
          selected={selected} onSelect={setSelected} />
        {selected != null && <StationDetail stations={stations} index={selected} hour={hour} weekend={weekend} />}
        <Busiest stations={stations} hour={hour} weekend={weekend} onSelect={setSelected} />
      </section>
      {data.history && <History history={data.history} />}
    </>
  );
}
