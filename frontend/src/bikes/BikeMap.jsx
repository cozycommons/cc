import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Minus, Plus, LocateFixed, X } from 'lucide-react';
import { useBasemap } from './basemap.js';
import { getJson, percent } from './live.js';
import { matches, searchWords } from './Plan.jsx';

const W = 360;
const H = 420;
const M_PER_DEG = 111320;
// The view is a center and `r`, the meters from the center to the left and right edges.
const MIN_R = 200;
const MAX_R = 3000;
const clampR = (r) => Math.min(MAX_R, Math.max(MIN_R, r));

// Status colors with a text label in the legend, never color alone.
export const LEVELS = [
  { key: 'ok', label: '3+', color: '#0ca30c' },
  { key: 'low', label: '1–2', color: '#fab219' },
  { key: 'out', label: 'No', color: '#d03b3b' },
  { key: 'closed', label: 'Closed', color: '#9a8f82' },
  // Drawn hollow: its counts are at least 15 minutes old.
  { key: 'unknown', label: 'No recent report', color: '#9a8f82' },
];
const COLOR = Object.fromEntries(LEVELS.map((l) => [l.key, l.color]));
const COUNT = { dock: 'docks', ebike: 'ebikes', bike: 'bikes' };

export function level(stations, i, need) {
  if (stations.flags[i] & 4) return 'unknown';
  const serving = need === 'dock' ? stations.flags[i] & 2 : stations.flags[i] & 1;
  if (!serving) return 'closed';
  const count = stations[COUNT[need]][i];
  return count >= 3 ? 'ok' : count > 0 ? 'low' : 'out';
}

export function project(view, lng, lat) {
  const k = Math.cos((view.lat * Math.PI) / 180);
  const s = W / 2 / view.r;
  return [W / 2 + (lng - view.lng) * M_PER_DEG * k * s, H / 2 - (lat - view.lat) * M_PER_DEG * s];
}

export function unproject(view, x, y) {
  const k = Math.cos((view.lat * Math.PI) / 180);
  const s = W / 2 / view.r;
  return { lng: view.lng + (x - W / 2) / (M_PER_DEG * k * s), lat: view.lat - (y - H / 2) / (M_PER_DEG * s) };
}

// Drawn bottom to top. Minor streets and bike lanes drop out when zoomed far out.
const STREETS = [['sea', 'bk-street--sea', 0], ['water', 'bk-street--water', 0], ['park', 'bk-street--park', 0],
  ['minor', 'bk-street--minor', 1500], ['major', 'bk-street--major', 0], ['bike', 'bk-street--bike', 1500]];

function Popup({ stations, index, need, view, transform, onPlan, onClose }) {
  const [odds, setOdds] = useState(null);
  const id = stations.id[index];
  useEffect(() => {
    let live = true;
    setOdds(null);
    getJson(`stations/${encodeURIComponent(id)}`).then((body) => { if (live) setOdds(body); }, () => {});
    return () => { live = false; };
  }, [id]);
  const [x0, y0] = project(view, stations.lng[index], stations.lat[index]);
  const x = transform.s * x0 + transform.tx, y = transform.s * y0 + transform.ty;
  const station = { name: stations.name[index], lat: stations.lat[index], lng: stations.lng[index] };
  const classic = stations.bikes[index] - stations.ebikes[index];
  const chance = odds?.chance?.[need];
  return (
    <div className={`bk-pop${y < 170 ? ' is-below' : ''}`} role="dialog" aria-label={station.name}
      style={{ left: `${(Math.min(W - 20, Math.max(20, x)) / W) * 100}%`, top: `${(y / H) * 100}%` }}>
      <div className="bk-pop__head">
        <b>{station.name}</b>
        <button type="button" className="bk-pop__close" onClick={onClose} aria-label="Close"><X size={16} aria-hidden="true" /></button>
      </div>
      <p className="bk-pop__counts">
        <span><b>{classic}</b> classic</span><span><b>{stations.ebikes[index]}</b> e-bike</span><span><b>{stations.docks[index]}</b> docks</span>
      </p>
      {chance && chance['15_min'] != null && (
        <p className="bk-pop__odds">{need === 'dock' ? 'A dock' : need === 'ebike' ? 'An e-bike' : 'A bike'} here in 15 min: <b>{percent(chance['15_min'])}</b> · 30 min: <b>{percent(chance['30_min'])}</b></p>
      )}
      {level(stations, index, need) === 'unknown' && <p className="bk-pop__odds is-stale">No recent report from this station.</p>}
      <div className="bk-pop__actions">
        <button type="button" className="cc-button cc-button--small cc-button--secondary" onClick={() => onPlan('from', station)}>Plan from here</button>
        <button type="button" className="cc-button cc-button--small cc-button--secondary" onClick={() => onPlan('to', station)}>Plan to here</button>
      </div>
    </div>
  );
}

// A map you can drag, pinch, scroll and tap: live stations over the street tiles.
// While a gesture runs, the drawing moves by a CSS transform; it is redrawn for the
// new view when the gesture ends, so phones stay smooth.
export default function BikeMap({ stations, need, home, focus, highlight = [], onPlan }) {
  const [view, setView] = useState(() => ({ lat: focus?.lat ?? home.lat, lng: focus?.lng ?? home.lng, r: clampR(focus?.radius ?? 700) }));
  const [transform, setTransformState] = useState({ tx: 0, ty: 0, s: 1 });
  // The live transform is also kept in a ref so commits read it without side effects in updaters.
  const live = useRef(transform);
  const setTransform = useCallback((next) => {
    live.current = typeof next === 'function' ? next(live.current) : next;
    setTransformState(live.current);
  }, []);
  const [selected, setSelected] = useState(() => focus?.station ?? null);
  const [query, setQuery] = useState('');
  const svg = useRef(null);
  const gesture = useRef(null);
  const pointers = useRef(new Map());
  const wheelTimer = useRef(null);

  const pad = view.r * 1.3 / M_PER_DEG;
  const k = Math.cos((view.lat * Math.PI) / 180);
  const streets = useBasemap(view.lat - pad * (H / W), view.lng - pad / k, view.lat + pad * (H / W), view.lng + pad / k);
  const paths = useMemo(() => {
    if (!streets) return [];
    const toPath = (line) => line.map(([lng, lat], i) => {
      const [x, y] = project(view, lng, lat);
      return `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`;
    }).join('');
    return STREETS.filter(([layer, , hideAbove]) => streets[layer] && (!hideAbove || view.r <= hideAbove))
      .map(([layer, className]) => [layer, className, streets[layer].map(toPath).join('')]);
  }, [streets, view]);

  const near = useMemo(() => {
    const out = [];
    stations.lat.forEach((lat, i) => {
      const [x, y] = project(view, stations.lng[i], lat);
      if (x > -60 && x < W + 60 && y > -60 && y < H + 60) out.push([i, x, y]);
    });
    return out;
  }, [stations, view]);

  const commit = useCallback(() => {
    const t = live.current;
    if (t.s === 1 && t.tx === 0 && t.ty === 0) return;
    setView((v) => ({ ...unproject(v, (W / 2 - t.tx) / t.s, (H / 2 - t.ty) / t.s), r: clampR(v.r / t.s) }));
    setTransform({ tx: 0, ty: 0, s: 1 });
  }, [setTransform]);

  const svgPoint = (event) => {
    const box = svg.current.getBoundingClientRect();
    return [((event.clientX - box.left) / box.width) * W, ((event.clientY - box.top) / box.height) * H];
  };
  // Scale limits keep the committed view within MIN_R..MAX_R.
  const boundScale = (s) => Math.min(view.r / MIN_R, Math.max(view.r / MAX_R, s));

  const onPointerDown = (event) => {
    svg.current.setPointerCapture?.(event.pointerId);
    pointers.current.set(event.pointerId, svgPoint(event));
    const pts = [...pointers.current.values()];
    gesture.current = {
      t0: live.current, moved: false,
      p0: pts[0],
      m0: pts.length === 2 ? [(pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2] : null,
      d0: pts.length === 2 ? Math.hypot(pts[0][0] - pts[1][0], pts[0][1] - pts[1][1]) : null,
    };
  };
  const onPointerMove = (event) => {
    if (!pointers.current.has(event.pointerId) || !gesture.current) return;
    pointers.current.set(event.pointerId, svgPoint(event));
    const pts = [...pointers.current.values()];
    const g = gesture.current;
    if (pts.length === 1 && !g.m0) {
      const dx = pts[0][0] - g.p0[0], dy = pts[0][1] - g.p0[1];
      if (Math.hypot(dx, dy) > 4) g.moved = true;
      setTransform({ ...g.t0, tx: g.t0.tx + dx, ty: g.t0.ty + dy });
    } else if (pts.length === 2 && g.m0) {
      g.moved = true;
      const m = [(pts[0][0] + pts[1][0]) / 2, (pts[0][1] + pts[1][1]) / 2];
      const s = boundScale(g.t0.s * (Math.hypot(pts[0][0] - pts[1][0], pts[0][1] - pts[1][1]) / g.d0));
      const f = s / g.t0.s;
      setTransform({ s, tx: m[0] - (g.m0[0] - g.t0.tx) * f, ty: m[1] - (g.m0[1] - g.t0.ty) * f });
    }
  };
  const onPointerUp = (event) => {
    const g = gesture.current;
    const point = pointers.current.get(event.pointerId);
    pointers.current.delete(event.pointerId);
    if (pointers.current.size > 0) {
      // A pinch became a drag: restart from the remaining finger.
      gesture.current = { t0: live.current, moved: true, p0: [...pointers.current.values()][0], m0: null, d0: null };
      return;
    }
    gesture.current = null;
    if (g && !g.moved && point) {
      // A tap: the nearest station within reach, in the drawing's own coordinates.
      const t = live.current;
      const qx = (point[0] - t.tx) / t.s, qy = (point[1] - t.ty) / t.s;
      let best = null, bestD = (20 / t.s) ** 2;
      for (const [i, x, y] of near) {
        const d = (x - qx) ** 2 + (y - qy) ** 2;
        if (d < bestD) { best = i; bestD = d; }
      }
      setSelected(best == null ? null : stations.id[best]);
    }
    commit();
  };
  const zoomAt = (factor, cx = W / 2, cy = H / 2) => {
    setTransform((t) => {
      const s = Math.min(view.r / MIN_R, Math.max(view.r / MAX_R, t.s * factor));
      const f = s / t.s;
      return { s, tx: cx - (cx - t.tx) * f, ty: cy - (cy - t.ty) * f };
    });
  };
  const onWheel = (event) => {
    event.preventDefault();
    const [cx, cy] = svgPoint(event);
    zoomAt(Math.exp(-event.deltaY * 0.0015), cx, cy);
    clearTimeout(wheelTimer.current);
    wheelTimer.current = setTimeout(commit, 180);
  };
  // React registers wheel listeners as passive, so preventDefault needs a native listener.
  useEffect(() => {
    const node = svg.current;
    node.addEventListener('wheel', onWheel, { passive: false });
    return () => node.removeEventListener('wheel', onWheel);
  });
  const button = (factor) => { zoomAt(factor); setTimeout(commit, 0); };
  const onKeyDown = (event) => {
    const step = 40;
    const moves = { ArrowLeft: [step, 0], ArrowRight: [-step, 0], ArrowUp: [0, step], ArrowDown: [0, -step] };
    if (moves[event.key]) {
      event.preventDefault();
      setTransform((t) => ({ ...t, tx: t.tx + moves[event.key][0], ty: t.ty + moves[event.key][1] }));
      setTimeout(commit, 0);
    } else if (event.key === '+' || event.key === '=') button(1.5);
    else if (event.key === '-') button(1 / 1.5);
  };
  const flyTo = (lat, lng, r, id = null) => {
    setTransform({ tx: 0, ty: 0, s: 1 });
    setView({ lat, lng, r: clampR(r) });
    setSelected(id);
  };

  const found = useMemo(() => {
    const words = searchWords(query);
    if (!words.length) return [];
    return stations.name.map((name, i) => [name, i]).filter(([name]) => matches(name, words)).slice(0, 6);
  }, [query, stations]);

  const selectedIndex = selected == null ? -1 : stations.id.indexOf(selected);
  const marked = new Set(highlight);
  const dot = Math.min(9, Math.max(3.5, 9 * (700 / view.r)));
  const width = Math.min(1.6, Math.max(0.45, 700 / view.r));
  const noun = need === 'dock' ? 'open docks' : need === 'ebike' ? 'e-bikes' : 'bikes';
  const [hx, hy] = project(view, home.lng, home.lat);

  return (
    <figure className="bk-map2">
      <div className="bk-map2__search">
        <input className="cc-input" type="search" placeholder="Find a station or street" aria-label="Find a station on the map"
          value={query} onChange={(e) => setQuery(e.target.value)} />
        {found.length > 0 && (
          <ul className="bk-search__results">
            {found.map(([name, i]) => (
              <li key={stations.id[i]}>
                <button type="button" onClick={() => { flyTo(stations.lat[i], stations.lng[i], 400, stations.id[i]); setQuery(''); }}>{name}</button>
              </li>
            ))}
          </ul>
        )}
      </div>
      <div className="bk-map2__frame">
        <svg ref={svg} viewBox={`0 0 ${W} ${H}`} role="img" tabIndex={0} onKeyDown={onKeyDown}
          aria-label={`Map of Citi Bike stations colored by ${noun}. Drag to move, pinch or scroll to zoom, tap a station for details.`}
          onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}>
          <g transform={`translate(${transform.tx} ${transform.ty}) scale(${transform.s})`} style={{ '--w': width }}>
            {paths.map(([layer, className, d]) => (
              <path key={layer} className={`bk-street ${className}`} d={d} />
            ))}
            {near.map(([i, x, y]) => {
              const id = stations.id[i];
              const lvl = level(stations, i, need);
              const labeled = marked.has(id) || id === selected || view.r <= 450;
              const r = labeled ? 11 : dot;
              return (
                <g key={id} className={`bk-dot${id === selected ? ' is-selected' : ''}${marked.has(id) ? ' is-marked' : ''}`}>
                  {lvl === 'unknown'
                    ? <circle className="bk-local__unknown" cx={x} cy={y} r={r - 1} />
                    : <circle cx={x} cy={y} r={r} fill={COLOR[lvl]} />}
                  {labeled && <text x={x} y={y + 4} textAnchor="middle">{stations[COUNT[need]][i]}</text>}
                </g>
              );
            })}
            <circle className="bk-local__you" cx={hx} cy={hy} r="7" />
          </g>
        </svg>
        <div className="bk-map2__controls">
          <button type="button" onClick={() => button(1.5)} aria-label="Zoom in"><Plus size={18} aria-hidden="true" /></button>
          <button type="button" onClick={() => button(1 / 1.5)} aria-label="Zoom out"><Minus size={18} aria-hidden="true" /></button>
          <button type="button" onClick={() => flyTo(home.lat, home.lng, 700)} aria-label="Back to you"><LocateFixed size={18} aria-hidden="true" /></button>
        </div>
        {selectedIndex >= 0 && (
          <Popup stations={stations} index={selectedIndex} need={need} view={view} transform={transform}
            onPlan={onPlan} onClose={() => setSelected(null)} />
        )}
      </div>
      <figcaption>
        <ul className="bk-legend bk-legend--ramp" aria-label={noun}>
          {LEVELS.map((l) => (
            <li key={l.key}>
              <i className={l.key === 'unknown' ? 'bk-legend__unknown' : undefined}
                style={l.key === 'unknown' ? undefined : { background: l.color }} />
              {['closed', 'unknown'].includes(l.key) ? l.label : `${l.label} ${noun}`}
            </li>
          ))}
          <li><i className="bk-legend__you" />You</li>
        </ul>
        {streets && <p className="bk-local__credit">Map data {streets.attribution}</p>}
      </figcaption>
    </figure>
  );
}
