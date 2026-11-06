import React, { useRef, useState } from 'react';

const W = 640;
const PAD = { top: 12, right: 12, bottom: 26, left: 48 };

function niceMax(value) {
  if (value <= 0) return 1;
  const step = 10 ** Math.floor(Math.log10(value));
  return [1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10].map((m) => m * step).find((m) => m >= value);
}

// Lines over a shared x axis with a snapping crosshair; one tooltip lists every series.
export default function LineChart({ series, xLabels, xTicks, formatY, height = 220, label, tickLabel = (l) => l }) {
  const [hover, setHover] = useState(null);
  const svg = useRef(null);
  const n = xLabels.length;
  const top = niceMax(Math.max(...series.flatMap((s) => s.values)));
  const x = (i) => PAD.left + (n > 1 ? (i / (n - 1)) * (W - PAD.left - PAD.right) : 0);
  const y = (v) => height - PAD.bottom - (v / top) * (height - PAD.top - PAD.bottom);
  const ticks = [0, top / 2, top];
  const point = (event) => {
    const box = svg.current.getBoundingClientRect();
    const px = ((event.clientX - box.left) / box.width) * W;
    setHover(Math.max(0, Math.min(n - 1, Math.round(((px - PAD.left) / (W - PAD.left - PAD.right)) * (n - 1)))));
  };
  return (
    <figure className="bk-chart">
      {series.length > 1 && (
        <ul className="bk-legend">
          {series.map((s) => <li key={s.key}><i style={{ background: s.color }} />{s.label}</li>)}
        </ul>
      )}
      <div className="bk-chart__plot">
        <svg ref={svg} viewBox={`0 0 ${W} ${height}`} role="img" aria-label={label}
          onPointerMove={point} onPointerLeave={() => setHover(null)}>
          {ticks.map((t) => (
            <g key={t}>
              <line className="bk-grid" x1={PAD.left} x2={W - PAD.right} y1={y(t)} y2={y(t)} />
              <text className="bk-axis" x={PAD.left - 6} y={y(t) + 4} textAnchor="end">{formatY(t)}</text>
            </g>
          ))}
          {xTicks.map((i) => (
            <text key={i} className="bk-axis" x={x(i)} y={height - 8} textAnchor="middle">{tickLabel(xLabels[i])}</text>
          ))}
          {series.map((s) => (
            <polyline key={s.key} fill="none" stroke={s.color} strokeWidth="2" strokeLinejoin="round"
              points={s.values.map((v, i) => `${x(i)},${y(v)}`).join(' ')} />
          ))}
          {hover != null && (
            <g>
              <line className="bk-crosshair" x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={height - PAD.bottom} />
              {series.map((s) => (
                <circle key={s.key} cx={x(hover)} cy={y(s.values[hover])} r="4" fill={s.color} className="bk-dot" />
              ))}
            </g>
          )}
        </svg>
        {hover != null && (
          <div className="bk-tooltip" style={{ left: `${(x(hover) / W) * 100}%` }}>
            <b className="bk-tooltip__title">{xLabels[hover]}</b>
            {series.map((s) => (
              <span key={s.key}><i style={{ background: s.color }} /><strong>{formatY(s.values[hover], true)}</strong> {s.label}</span>
            ))}
          </div>
        )}
      </div>
    </figure>
  );
}
