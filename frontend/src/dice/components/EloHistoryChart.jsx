import React from 'react';
import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, CartesianGrid, Tooltip } from 'recharts';
import { formatDate } from '../utils.js';

// Matches --accent-primary / --border-subtle / --text-tertiary from
// dice-theme.css. The Dice app doesn't wire up a dark mode toggle yet (no
// data-theme is ever set on .jk-dice), so light-mode literals are safe here
// the same way they'd be read off the CSS variables.
const LINE_COLOR = '#B0512E';
const GRID_COLOR = '#E2D9C8';
const AXIS_COLOR = '#7A7480';

function formatAxisTick(dateString) {
  return new Date(dateString).toLocaleDateString(undefined, { month: 'short', day: 'numeric' });
}

function EloTooltip({ active, payload }) {
  if (!active || !payload?.length) return null;
  const point = payload[0].payload;
  return (
    <div
      style={{
        background: '#FFFFFF',
        border: `1px solid ${GRID_COLOR}`,
        borderRadius: 6,
        padding: '6px 10px',
      }}
    >
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: AXIS_COLOR }}>
        {formatDate(point.date)}
      </div>
      <div style={{ fontFamily: 'var(--font-mono)', fontSize: 13, fontWeight: 600, color: 'var(--text-primary)' }}>
        {point.elo} ELO
      </div>
    </div>
  );
}

export default function EloHistoryChart({ history }) {
  const values = history.map((p) => p.elo);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const padding = Math.max(Math.round((max - min) * 0.15), 10);
  const domain = [min - padding, max + padding];

  return (
    <div style={{ width: '100%', height: 180 }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={history} margin={{ top: 8, right: 16, left: 0, bottom: 0 }}>
          <CartesianGrid vertical={false} stroke={GRID_COLOR} />
          <XAxis
            dataKey="date"
            tickFormatter={formatAxisTick}
            tick={{ fill: AXIS_COLOR, fontSize: 10, fontFamily: 'var(--font-mono)' }}
            axisLine={{ stroke: GRID_COLOR }}
            tickLine={false}
            padding={{ left: 12, right: 12 }}
            minTickGap={32}
          />
          <YAxis
            domain={domain}
            tick={{ fill: AXIS_COLOR, fontSize: 10, fontFamily: 'var(--font-mono)' }}
            axisLine={false}
            tickLine={false}
            width={36}
          />
          <Tooltip content={<EloTooltip />} cursor={{ stroke: GRID_COLOR, strokeWidth: 1 }} />
          <Line
            type="monotone"
            dataKey="elo"
            stroke={LINE_COLOR}
            strokeWidth={2}
            strokeLinecap="round"
            dot={false}
            activeDot={{ r: 4, fill: LINE_COLOR, stroke: '#FFFFFF', strokeWidth: 2 }}
            isAnimationActive={false}
          />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
