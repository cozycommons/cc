import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Minus, Plus, MapPin } from 'lucide-react';
import { useBasemap } from './basemap.js';

// Default drawing size; the map takes its container's size once measured.
const W = 360;
const H = 420;
const M_PER_DEG = 111320;
// The view is a center and `r`, the meters from the center to the left and right edges.
const MIN_R = 150;
const MAX_R = 3000;
const clampR = (r) => Math.min(MAX_R, Math.max(MIN_R, r));
// Street names show at walking zoom; station names at street zoom.
const NAMES_BELOW_R = 1300;
const STATION_NAMES_BELOW_R = 520;

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
const TONE = { go: '#2f6b2f', likely: '#4d6a2a', risky: '#b07a00', skip: '#a3302f', unknown: '#9a8f82' };

export function level(stations, i, need) {
  if (stations.flags[i] & 4) return 'unknown';
  const serving = need === 'dock' ? stations.flags[i] & 2 : stations.flags[i] & 1;
  if (!serving) return 'closed';
  const count = stations[COUNT[need]][i];
  return count >= 3 ? 'ok' : count > 0 ? 'low' : 'out';
}

export function project(view, lng, lat) {
  const w = view.w ?? W, h = view.h ?? H;
  const k = Math.cos((view.lat * Math.PI) / 180);
  const s = w / 2 / view.r;
  return [w / 2 + (lng - view.lng) * M_PER_DEG * k * s, h / 2 - (lat - view.lat) * M_PER_DEG * s];
}

export function unproject(view, x, y) {
  const w = view.w ?? W, h = view.h ?? H;
  const k = Math.cos((view.lat * Math.PI) / 180);
  const s = w / 2 / view.r;
  return { lng: view.lng + (x - w / 2) / (M_PER_DEG * k * s), lat: view.lat - (y - h / 2) / (M_PER_DEG * s) };
}

// The view that shows every point inside the part of the map left uncovered by
// floating controls and the sheet: `inset` is { top, left } in pixels and
// `bottom`, the fraction of the height the sheet covers. With some margin.
export function fitView(points, w, h, inset = {}) {
  const { top = 0, left = 0, bottom = 0 } = inset;
  const lats = points.map((p) => p.lat), lngs = points.map((p) => p.lng);
  const lat = (Math.min(...lats) + Math.max(...lats)) / 2, lng = (Math.min(...lngs) + Math.max(...lngs)) / 2;
  const k = Math.cos((lat * Math.PI) / 180);
  const spanX = (Math.max(...lngs) - Math.min(...lngs)) * M_PER_DEG * k;
  const spanY = (Math.max(...lats) - Math.min(...lats)) * M_PER_DEG;
  const free = Math.max(80, h * (1 - bottom) - top);
  const freeW = Math.max(80, w - left);
  // r is half the width in meters: fit the span in 75% of the free width and height.
  const r = clampR(Math.max((spanX / (0.75 * freeW)) * w, (spanY / (0.75 * free)) * w) / 2);
  const mPerPx = (2 * r) / w;
  // Move the center so the points sit in the middle of the uncovered area.
  const shiftY = (h / 2 - (top + free / 2)) * mPerPx;
  const shiftX = (w / 2 - (left + freeW / 2)) * mPerPx;
  return { lat: lat - shiftY / M_PER_DEG, lng: lng + shiftX / (M_PER_DEG * k), r };
}

// Drawn bottom to top. Minor streets and bike lanes drop out when zoomed far out.
const STREETS = [['sea', 'bk-street--sea', 0], ['water', 'bk-street--water', 0], ['park', 'bk-street--park', 0],
  ['minor', 'bk-street--minor', 1500], ['major', 'bk-street--major', 0], ['bike', 'bk-street--bike', 1500]];

// Street names that fit: none overlapping, and one per name within about 170 px.
function placeNames(names, view, w, h) {
  if (!names || view.r > NAMES_BELOW_R) return [];
  const placed = [];
  for (const n of names) {
    const [x, y] = project({ ...view, w, h }, n.lng, n.lat);
    if (x < 20 || x > w - 20 || y < 20 || y > h - 20) continue;
    const half = n.text.length * 3.1 + 4;
    const clash = placed.some((p) => {
      const d = Math.hypot(p.x - x, p.y - y);
      return d < half + p.half || (p.text === n.text && d < 170);
    });
    if (!clash) placed.push({ ...n, x, y, half });
    if (placed.length >= 70) break;
  }
  return placed;
}

// A map you can drag, pinch, scroll and tap: live stations over the street tiles,
// with street names. While a gesture runs, the drawing moves by a CSS transform; it
// is redrawn for the new view when the gesture ends, so phones stay smooth.
//
// `home` is the point answers are from (you, a searched place, a dropped pin), or
// null; `you` is your own location when known. `routes` draws lines from one
// point to stations with a time on each ({ from, to: [{ lat, lng, id, label, tone,
// best, ride }] }). `fit` ({ key, points }) moves the view to show those points
// clear of the controls and sheet (`inset`, see fitView). Tapping a station
// selects it (`onSelect`); tapping anywhere else drops a pin with "Check from
// here" (`onPin`).
export default function BikeMap({
  stations, need, home, you = null, center, focus, highlight = [], selected = null, routes = null, fit = null,
  inset = {}, onSelect, onPin,
}) {
  const start = focus ?? home ?? center;
  const [view, setView] = useState(() => ({ lat: start.lat, lng: start.lng, r: clampR(focus?.radius ?? 700) }));
  const [size, setSize] = useState({ w: W, h: H });
  const [transform, setTransformState] = useState({ tx: 0, ty: 0, s: 1 });
  // The live transform is also kept in a ref so commits read it without side effects in updaters.
  const live = useRef(transform);
  const setTransform = useCallback((next) => {
    live.current = typeof next === 'function' ? next(live.current) : next;
    setTransformState(live.current);
  }, []);
  const [pin, setPin] = useState(null);
  const frame = useRef(null);
  const svg = useRef(null);
  const gesture = useRef(null);
  const pointers = useRef(new Map());
  const wheelTimer = useRef(null);
  const { w, h } = size;
  const v = useMemo(() => ({ ...view, w, h }), [view, w, h]);

  useLayoutEffect(() => {
    const node = frame.current;
    if (!node || typeof ResizeObserver === 'undefined') return undefined;
    const measure = () => {
      const box = node.getBoundingClientRect();
      if (box.width > 0 && box.height > 0) setSize({ w: Math.round(box.width), h: Math.round(box.height) });
    };
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const pad = view.r * 1.3 / M_PER_DEG;
  const k = Math.cos((view.lat * Math.PI) / 180);
  const streets = useBasemap(view.lat - pad * (h / w), view.lng - pad / k, view.lat + pad * (h / w), view.lng + pad / k);
  const paths = useMemo(() => {
    if (!streets) return [];
    const toPath = (line) => line.map(([lng, lat], i) => {
      const [x, y] = project(v, lng, lat);
      return `${i ? 'L' : 'M'}${x.toFixed(1)} ${y.toFixed(1)}`;
    }).join('');
    return STREETS.filter(([layer, , hideAbove]) => streets[layer] && (!hideAbove || view.r <= hideAbove))
      .map(([layer, className]) => [layer, className, streets[layer].map(toPath).join('')]);
  }, [streets, v, view.r]);
  const names = useMemo(() => placeNames(streets?.names, view, w, h), [streets, view, w, h]);

  const near = useMemo(() => {
    const out = [];
    stations.lat.forEach((lat, i) => {
      const [x, y] = project(v, stations.lng[i], lat);
      if (x > -60 && x < w + 60 && y > -60 && y < h + 60) out.push([i, x, y]);
    });
    return out;
  }, [stations, v, w, h]);

  const commit = useCallback(() => {
    const t = live.current;
    if (t.s === 1 && t.tx === 0 && t.ty === 0) return;
    setView((old) => ({ ...unproject({ ...old, w, h }, (w / 2 - t.tx) / t.s, (h / 2 - t.ty) / t.s), r: clampR(old.r / t.s) }));
    setTransform({ tx: 0, ty: 0, s: 1 });
  }, [setTransform, w, h]);

  const svgPoint = (event) => {
    const box = svg.current.getBoundingClientRect();
    return [((event.clientX - box.left) / box.width) * w, ((event.clientY - box.top) / box.height) * h];
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
      let best = null, bestD = (22 / t.s) ** 2;
      for (const [i, x, y] of near) {
        const d = (x - qx) ** 2 + (y - qy) ** 2;
        if (d < bestD) { best = i; bestD = d; }
      }
      if (best != null) {
        setPin(null);
        onSelect?.(stations.id[best]);
      } else if (onPin) {
        setPin(unproject(v, qx, qy));
      }
    }
    commit();
  };
  const zoomAt = (factor, cx = w / 2, cy = h / 2) => {
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
  const flyTo = useCallback((next) => {
    setTransform({ tx: 0, ty: 0, s: 1 });
    setView((old) => ({ ...old, ...next, r: clampR(next.r ?? old.r) }));
  }, [setTransform]);

  // A new starting point (search, pin, locate) recenters the map on it.
  const first = useRef(true);
  useEffect(() => {
    if (first.current) { first.current = false; return; }
    if (!home) return;
    setPin(null);
    flyTo({ lat: home.lat, lng: home.lng });
  }, [home?.lat, home?.lng, flyTo]); // eslint-disable-line react-hooks/exhaustive-deps
  // Routes to show: fit them above the sheet once per key, then leave the view to the user.
  useEffect(() => {
    if (!fit?.points?.length) return;
    flyTo(fitView(fit.points, w, h, inset));
  }, [fit?.key, w, h]); // eslint-disable-line react-hooks/exhaustive-deps

  const marked = new Set(highlight);
  const routeIds = new Set(routes?.to.map((t) => t.id) ?? []);
  const dot = Math.min(9, Math.max(3.5, 9 * (700 / view.r)));
  const width = Math.min(1.6, Math.max(0.45, 700 / view.r));
  const noun = need === 'dock' ? 'open docks' : need === 'ebike' ? 'e-bikes' : 'bikes';
  const [hx, hy] = home ? project(v, home.lng, home.lat) : [null, null];
  const [yx, yy] = you ? project(v, you.lng, you.lat) : [null, null];
  const [px, py] = pin ? project(v, pin.lng, pin.lat) : [null, null];
  const away = you && home && (Math.abs(you.lat - home.lat) > 1e-5 || Math.abs(you.lng - home.lng) > 1e-5);
  const [fx, fy] = routes ? project(v, routes.from.lng, routes.from.lat) : [null, null];

  return (
    <figure className="bk-map2">
      <div className="bk-map2__frame" ref={frame}>
        <svg ref={svg} viewBox={`0 0 ${w} ${h}`} role="img" tabIndex={0} onKeyDown={onKeyDown}
          className={routes ? 'has-routes' : undefined}
          aria-label={`Map of Citi Bike stations colored by ${noun}. Drag to move, pinch or scroll to zoom, tap a station to check it, or anywhere else to check from there.`}
          onPointerDown={onPointerDown} onPointerMove={onPointerMove} onPointerUp={onPointerUp} onPointerCancel={onPointerUp}>
          <g transform={`translate(${transform.tx} ${transform.ty}) scale(${transform.s})`} style={{ '--w': width }}>
            {paths.map(([layer, className, d]) => (
              <path key={layer} className={`bk-street ${className}`} d={d} />
            ))}
            {names.map((n) => (
              <text key={`${n.text}${n.x.toFixed(0)}${n.y.toFixed(0)}`} className="bk-street-name" x={n.x} y={n.y}
                transform={`rotate(${n.deg} ${n.x} ${n.y})`} textAnchor="middle" dominantBaseline="central">{n.text}</text>
            ))}
            {routes && routes.to.map((t) => {
              const [x, y] = project(v, t.lng, t.lat);
              return (
                <line key={`line-${t.id}`} className={`bk-route${t.best ? ' is-best' : ''}${t.ride ? ' is-ride' : ''}`}
                  x1={fx} y1={fy} x2={x} y2={y} style={{ stroke: TONE[t.tone] ?? TONE.unknown }} />
              );
            })}
            {near.map(([i, x, y]) => {
              const id = stations.id[i];
              const lvl = level(stations, i, need);
              const inRoute = routeIds.has(id) || id === selected;
              const labeled = marked.has(id) || inRoute || view.r <= 450;
              const r = labeled ? 11 : dot;
              return (
                <g key={id} className={`bk-dot${id === selected ? ' is-selected' : ''}${marked.has(id) ? ' is-marked' : ''}${routes && !inRoute ? ' is-dim' : ''}`}>
                  {lvl === 'unknown'
                    ? <circle className="bk-local__unknown" cx={x} cy={y} r={r - 1} />
                    : <circle cx={x} cy={y} r={r} fill={COLOR[lvl]} />}
                  {labeled && <text x={x} y={y + 4} textAnchor="middle">{stations[COUNT[need]][i]}</text>}
                  {(id === selected || (inRoute && view.r <= STATION_NAMES_BELOW_R)) && (
                    <text className="bk-dot__name" x={x} y={y + 24} textAnchor="middle">{stations.name[i]}</text>
                  )}
                </g>
              );
            })}
            {routes && routes.to.map((t) => {
              const [x, y] = project(v, t.lng, t.lat);
              const label = t.label;
              const half = label.length * 3.6 + 8;
              return (
                <g key={`pill-${t.id}`} className={`bk-pill-time${t.best ? ' is-best' : ''}`} transform={`translate(${x} ${y - 25})`}>
                  <rect x={-half} y={-10} width={half * 2} height={20} rx={10} style={{ fill: t.best ? TONE[t.tone] : undefined }} />
                  <text textAnchor="middle" y={4}>{label}</text>
                </g>
              );
            })}
            {away && <circle className="bk-local__you" cx={yx} cy={yy} r="7" />}
            {home && (away || !you
              ? <path className="bk-local__from" d={`M${hx} ${hy}l-7 -14a8 8 0 1 1 14 0z`} />
              : <circle className="bk-local__you" cx={hx} cy={hy} r="7" />)}
            {pin && <path className="bk-local__pin" d={`M${px} ${py}l-7 -14a8 8 0 1 1 14 0z`} />}
          </g>
        </svg>
        <div className="bk-map2__controls">
          <button type="button" onClick={() => button(1.5)} aria-label="Zoom in"><Plus size={18} aria-hidden="true" /></button>
          <button type="button" onClick={() => button(1 / 1.5)} aria-label="Zoom out"><Minus size={18} aria-hidden="true" /></button>
          {home && (
            <button type="button" onClick={() => flyTo({ lat: home.lat, lng: home.lng, r: 700 })} aria-label="Back to the starting point">
              <MapPin size={18} aria-hidden="true" />
            </button>
          )}
        </div>
        {pin && (
          <button type="button" className="cc-button cc-button--small bk-pin-action"
            style={{ left: `${(Math.min(w - 70, Math.max(70, transform.s * px + transform.tx)) / w) * 100}%`,
              top: `${((transform.s * py + transform.ty) / h) * 100}%` }}
            onClick={() => { onPin({ lat: Number(pin.lat.toFixed(5)), lng: Number(pin.lng.toFixed(5)) }); setPin(null); }}>
            <MapPin size={16} aria-hidden="true" /> Check from here
          </button>
        )}
        {streets && <p className="bk-map2__credit">© OpenStreetMap</p>}
      </div>
    </figure>
  );
}
