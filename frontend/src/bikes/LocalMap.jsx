import React from 'react';

const SIZE = 360;
const RADIUS_M = 800;
const M_PER_DEG = 111320;

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

export function level(stations, i, need) {
  if (stations.flags[i] & 4) return 'unknown';
  const serving = need === 'dock' ? stations.flags[i] & 2 : stations.flags[i] & 1;
  if (!serving) return 'closed';
  const count = stations[need === 'dock' ? 'docks' : need === 'ebike' ? 'ebikes' : 'bikes'][i];
  return count >= 3 ? 'ok' : count > 0 ? 'low' : 'out';
}

export function countOf(stations, i, need) {
  return stations[need === 'dock' ? 'docks' : need === 'ebike' ? 'ebikes' : 'bikes'][i];
}

// Live stations within RADIUS_M of you, drawn to scale with you at the center.
export default function LocalMap({ stations, center, need, highlight, onSelect }) {
  const k = Math.cos((center.lat * Math.PI) / 180);
  const scale = SIZE / 2 / RADIUS_M;
  const near = [];
  stations.lat.forEach((lat, i) => {
    const dx = (stations.lng[i] - center.lng) * M_PER_DEG * k;
    const dy = (lat - center.lat) * M_PER_DEG;
    if (Math.abs(dx) < RADIUS_M && Math.abs(dy) < RADIUS_M) near.push([i, SIZE / 2 + dx * scale, SIZE / 2 - dy * scale]);
  });
  const noun = need === 'dock' ? 'open docks' : need === 'ebike' ? 'e-bikes' : 'bikes';
  return (
    <figure className="bk-local">
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} role="img" aria-label={`${near.length} stations within ${RADIUS_M} m, colored by ${noun}`}>
        <circle className="bk-local__ring" cx={SIZE / 2} cy={SIZE / 2} r={400 * scale} />
        {near.map(([i, x, y]) => {
          const id = stations.id[i];
          const marked = highlight.includes(id);
          return (
            <g key={id} className={`bk-local__station${marked ? ' is-marked' : ''}`} onClick={() => onSelect?.(id)}>
              <circle cx={x} cy={y} r="16" fill="transparent" />
              {level(stations, i, need) === 'unknown'
                ? <circle className="bk-local__unknown" cx={x} cy={y} r={marked ? 10 : 7} />
                : <circle cx={x} cy={y} r={marked ? 11 : 8} fill={COLOR[level(stations, i, need)]} />}
              {marked && <text x={x} y={y + 4} textAnchor="middle">{countOf(stations, i, need)}</text>}
            </g>
          );
        })}
        <circle className="bk-local__you" cx={SIZE / 2} cy={SIZE / 2} r="7" />
      </svg>
      <figcaption>
        <ul className="bk-legend bk-legend--ramp" aria-label={noun}>
          {LEVELS.map((l) => (
            <li key={l.key}>
              <i className={l.key === 'unknown' ? 'bk-legend__unknown' : undefined}
                style={l.key === 'unknown' ? undefined : { background: l.color }} />
              {['closed', 'unknown'].includes(l.key) ? l.label : `${l.label} ${noun}`}
            </li>
          ))}
          <li><i className="bk-legend__you" />You · ring 400 m</li>
        </ul>
      </figcaption>
    </figure>
  );
}
