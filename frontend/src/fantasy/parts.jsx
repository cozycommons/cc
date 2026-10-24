import React from 'react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { scorePath } from './paths.js';

export const COLORS = ['#b75f41', '#2a78d6'];
export const round = value => (Number.isFinite(value) ? Math.round(value) : '—');
export const pct = value => (Number.isFinite(value) ? `${value > 0 && value < 1 ? '<1' : Math.round(value)}%` : '—');
export const weekday = value => new Date(`${value}T12:00:00`).toLocaleDateString([], { weekday: 'short' });
export const longDay = value => new Date(`${value}T12:00:00`).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
export const tooltipStyle = { background: '#fffaf2', border: '1px solid #d6c5a7', borderRadius: 8, fontSize: 12 };

const initials = name => name.split(/\s+/).map(word => word[0]).join('').slice(0, 2).toUpperCase();

export function TeamLogo({ team, side, size = 28 }) {
  const [broken, setBroken] = React.useState(false);
  const style = { width: size, height: size, '--fx-side': COLORS[side] };
  return team.logo && !broken
    ? <img className="fx-logo" src={team.logo} alt="" style={style} referrerPolicy="no-referrer" onError={() => setBroken(true)} />
    : <span className="fx-logo fx-logo--initials" style={{ ...style, fontSize: size * 0.38 }} aria-hidden="true">{initials(team.name)}</span>;
}

export function ScorePath({ matchup, height = 150 }) {
  const rows = scorePath(matchup).map(row => ({
    date: row.date, a0: row.actual?.[0], a1: row.actual?.[1], p0: row.projected?.[0], p1: row.projected?.[1],
  }));
  const names = [matchup.home.name, matchup.away.name];
  return (
    <div className="fx-chart" style={{ height }} role="img" aria-label={`Cumulative score by day for ${names.join(' and ')}; dashed lines are projections`}>
      <ResponsiveContainer>
        <LineChart data={rows} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="#3d2f2914" vertical={false} />
          <XAxis dataKey="date" tickFormatter={weekday} tick={{ fill: '#75695b', fontSize: 11 }} tickLine={false} axisLine={false} />
          <YAxis width={38} tick={{ fill: '#75695b', fontSize: 11 }} tickLine={false} axisLine={false} />
          <Tooltip labelFormatter={longDay} contentStyle={tooltipStyle}
            formatter={(value, key) => [round(value), `${names[Number(key[1])]} ${key[0] === 'a' ? 'actual' : 'projected'}`]} />
          {[0, 1].map(side => (
            <React.Fragment key={side}>
              <Line dataKey={`a${side}`} stroke={COLORS[side]} strokeWidth={2.5} dot={{ r: 3 }} isAnimationActive={false} connectNulls={false} />
              <Line dataKey={`p${side}`} stroke={COLORS[side]} strokeWidth={2} strokeDasharray="5 4" dot={false} isAnimationActive={false} connectNulls={false} />
            </React.Fragment>
          ))}
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}

export function OddsTrend({ history }) {
  if (!history || history.length < 2) return null;
  const points = history.map((point, i) => `${(i / (history.length - 1) * 100).toFixed(1)},${(30 - point.chance * 0.3).toFixed(1)}`).join(' ');
  const change = history.at(-1).chance - history[0].chance;
  return (
    <span className="fx-trend">
      <svg viewBox="0 0 100 30" preserveAspectRatio="none" role="img" aria-label={`Home win chance from ${pct(history[0].chance)} to ${pct(history.at(-1).chance)}`}>
        <line x1="0" x2="100" y1="15" y2="15" /><polyline points={points} />
      </svg>
      {change > 0 ? '+' : ''}{Math.round(change)} since {weekday(history[0].date)}
    </span>
  );
}
