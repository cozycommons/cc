import React from 'react';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { scorePath } from './paths.js';

export const COLORS = ['#b75f41', '#2a78d6'];
export const round = value => (Number.isFinite(value) ? Math.round(value) : '—');
export const pct = value => (Number.isFinite(value) ? `${value > 0 && value < 1 ? '<1' : value > 99 && value < 100 ? '>99' : Math.round(value)}%` : '—');
// A matchup's win chance never reads 0% or 100% before the last game: upsets still happen.
export const winPct = (value, final = false) => (!final && Number.isFinite(value) && (value > 99 || value < 1) ? (value > 99 ? '>99%' : '<1%') : pct(value));
export const weekday = value => new Date(`${value}T12:00:00`).toLocaleDateString([], { weekday: 'short' });
export const longDay = value => new Date(`${value}T12:00:00`).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });
const NARROW = '(max-width: 600px)';

// Phones get summaries; charts and long lists wait until the reader asks for them.
export function useNarrow() {
  const [narrow, setNarrow] = React.useState(() => window.matchMedia?.(NARROW).matches ?? false);
  React.useEffect(() => {
    const query = window.matchMedia?.(NARROW);
    if (!query) return undefined;
    const update = () => setNarrow(query.matches);
    query.addEventListener('change', update);
    return () => query.removeEventListener('change', update);
  }, []);
  return narrow;
}

export const tooltipStyle = { background: '#fffaf2', border: '1px solid #d6c5a7', borderRadius: 8, fontSize: 12 };

export const OwnersContext = React.createContext(new Map());

// ESPN manager first name, or the linked Dice name and avatar once the owner confirms.
export function Manager({ team }) {
  const owner = React.useContext(OwnersContext).get(team.id);
  if (owner) {
    return (
      <span className="fx-manager fx-manager--linked">
        {owner.avatar && <img src={owner.avatar} alt="" referrerPolicy="no-referrer" />}{owner.name}
      </span>
    );
  }
  return team.manager ? <span className="fx-manager">{team.manager}</span> : null;
}

const initials = name => name.split(/\s+/).map(word => word[0]).join('').slice(0, 2).toUpperCase();

export function TeamLogo({ team, side, size = 28 }) {
  const [loaded, setLoaded] = React.useState(null);
  const [broken, setBroken] = React.useState(null);
  const style = { width: size, height: size, '--fx-side': COLORS[side], fontSize: Math.max(11, size * 0.38) };
  return (
    <span className="fx-logo fx-logo--initials fx-logo--lazy" style={style} aria-hidden="true">
      {initials(team.name)}
      {team.logo && broken !== team.logo && <img src={team.logo} alt="" loading="lazy" decoding="async"
        style={{ opacity: loaded === team.logo ? 1 : 0 }} referrerPolicy="no-referrer"
        onLoad={() => setLoaded(team.logo)} onError={() => setBroken(team.logo)} />}
    </span>
  );
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
          <XAxis dataKey="date" tickFormatter={weekday} tick={{ fill: 'var(--fx-text)', fontSize: 11 }} tickLine={false} axisLine={false} />
          <YAxis width={38} tick={{ fill: 'var(--fx-text)', fontSize: 11 }} tickLine={false} axisLine={false} />
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

// Win chance over time, spaced by when each estimate was saved.
export function OddsTrend({ history, name, wide = false, final = false }) {
  const mask = React.useId().replace(/:/g, '');
  if (!history || history.length < 2) return null;
  const start = history[0].time, span = Math.max(1, history.at(-1).time - start);
  const points = history.map(point => `${((point.time - start) / span * 100).toFixed(1)},${(30 - point.chance * 0.3).toFixed(1)}`).join(' ');
  const change = history.at(-1).chance - history[0].chance;
  return (
    <span className={`fx-trend${wide ? ' fx-trend--wide' : ''}`}>
      <svg viewBox="0 0 100 30" preserveAspectRatio="none" role="img" aria-label={`Home win chance from ${winPct(history[0].chance)} to ${winPct(history.at(-1).chance, final)}`}>
        <defs><mask id={mask}><rect className="fx-draw" x="0" y="-5" width="110" height="40" fill="white" /></mask></defs><line x1="0" x2="100" y1="15" y2="15" /><polyline points={points} mask={`url(#${mask})`} />
      </svg>
      <span>{name ? `${name} odds ` : ''}{change > 0 ? '+' : ''}{Math.round(change)} since {weekday(history[0].date)}</span>
    </span>
  );
}
