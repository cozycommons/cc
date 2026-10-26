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

const change = value => { const size = Math.round(Math.abs(value)); return size ? `${value > 0 ? '▲' : '▼'}${size}%` : ''; };

// Win odds over time as one line (the second team is always 100 minus the first): the top team's logo
// marks the top of the right edge and the other team's the bottom, so the line ends beside whoever is winning.
// The chart stays neutral; green and red only mean the leader's odds went up or down.
export function WinChart({ history, teams, final = false, big = false }) {
  const [cursor, setCursor] = React.useState(null);
  if (!history || history.length < 2) return null;
  const start = history[0].time, span = Math.max(1, history.at(-1).time - start);
  const x = point => (point.time - start) / span * 100;
  const y = point => 100 - point.chance;
  const points = history.map(point => `${x(point).toFixed(2)},${y(point).toFixed(2)}`).join(' ');
  const shown = cursor ?? history.at(-1);
  const leader = shown.chance >= 50 ? 0 : 1;
  const odds = side => (side ? 100 - shown.chance : shown.chance);
  const moved = (leader ? -1 : 1) * (shown.chance - history[0].chance);
  const days = big ? [...new Map(history.map(point => [point.date, point])).values()] : [];
  const step = event => {
    const moves = { ArrowLeft: -1, ArrowRight: 1, Home: -Infinity, End: Infinity };
    if (!(event.key in moves)) return;
    event.preventDefault();
    const index = history.indexOf(cursor ?? history.at(-1)) + moves[event.key];
    setCursor(history[Math.min(history.length - 1, Math.max(0, Number.isFinite(index) ? index : moves[event.key] < 0 ? 0 : history.length - 1))]);
  };
  const scrub = event => {
    if (!big) return;
    const box = event.currentTarget.getBoundingClientRect();
    const at = start + Math.min(1, Math.max(0, (event.clientX - box.left) / box.width)) * span;
    setCursor(history.reduce((best, point) => (Math.abs(point.time - at) < Math.abs(best.time - at) ? point : best)));
  };
  const name = side => teams?.[side]?.name ?? (side ? 'Away' : 'Home');
  return (
    <div className={`fx-win${big ? ' fx-win--big' : ''}`}>
      <p className="fx-win-head" aria-live={big ? 'polite' : undefined}>
        {teams && <TeamLogo team={teams[leader]} side={leader} size={18} />}
        {big && <span className="fx-win-name">{name(leader)}</span>}
        <b>{winPct(odds(leader), final)}</b>
        {change(moved) && <span className={moved > 0 ? 'fx-up' : 'fx-down'}>{change(moved)}</span>}
        <small>{cursor ? weekday(cursor.date) : `since ${weekday(history[0].date)}`}</small>
      </p>
      <div className="fx-win-body">
        <div className="fx-win-plot" onPointerMove={scrub} onPointerDown={scrub} onPointerLeave={() => setCursor(null)}
          {...(big && { tabIndex: 0, onKeyDown: step, onBlur: () => setCursor(null), 'aria-label': 'Win odds over time; use arrow keys to step through' })}>
          <div className="fx-win-area">
            <svg viewBox="0 0 100 100" preserveAspectRatio="none" role="img"
              aria-label={`${name(leader)} ${winPct(odds(leader), final)} to win; ${name(0)} at the top, ${name(1)} at the bottom`}>
              {big && [0, 100].map(edge => <line key={edge} className="fx-win-grid" x1="0" x2="100" y1={edge} y2={edge} />)}
              <polygon className="fx-win-fill" points={`0,50 ${points} 100,50`} />
              <line className="fx-win-mid" x1="0" x2="100" y1="50" y2="50" />
              {cursor && <line className="fx-win-cursor" x1={x(cursor)} x2={x(cursor)} y1="0" y2="100" />}
              <polyline points={points} />
            </svg>
            <i className="fx-win-dot" style={{ left: `${x(shown)}%`, top: `${y(shown)}%` }} />
          </div>
          {big && <div className="fx-win-axis">{days.map(point => <span key={point.date} style={{ left: `${x(point)}%`, transform: `translateX(-${x(point)}%)` }}>{weekday(point.date)}</span>)}</div>}
        </div>
        {teams && <span className="fx-win-ends" aria-hidden="true"><TeamLogo team={teams[0]} side={0} size={18} /><TeamLogo team={teams[1]} side={1} size={18} /></span>}
      </div>
    </div>
  );
}
