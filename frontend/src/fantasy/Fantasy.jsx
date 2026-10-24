import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { CartesianGrid, Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from 'recharts';
import { getUrl } from '../api.js';
import { favorite, orderMatchups, scorePath } from './paths.js';
import { loadSnapshot } from './source.js';
import './fantasy.css';

const COLORS = ['#b75f41', '#2a78d6'];
const round = value => (Number.isFinite(value) ? Math.round(value) : '—');
const pct = value => (Number.isFinite(value) ? `${Math.round(value)}%` : '—');
const weekday = value => new Date(`${value}T12:00:00`).toLocaleDateString([], { weekday: 'short' });
const longDay = value => new Date(`${value}T12:00:00`).toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' });

function ScorePath({ matchup }) {
  const rows = scorePath(matchup).map(row => ({
    date: row.date,
    a0: row.actual?.[0], a1: row.actual?.[1], p0: row.projected?.[0], p1: row.projected?.[1],
  }));
  const names = [matchup.home.name, matchup.away.name];
  return (
    <div className="fx-chart" role="img" aria-label={`Cumulative score by day for ${names.join(' and ')}; dashed lines are projections`}>
      <ResponsiveContainer>
        <LineChart data={rows} margin={{ top: 6, right: 8, left: 0, bottom: 0 }}>
          <CartesianGrid stroke="#3d2f2914" vertical={false} />
          <XAxis dataKey="date" tickFormatter={weekday} tick={{ fill: '#75695b', fontSize: 11 }} tickLine={false} axisLine={false} />
          <YAxis width={38} tick={{ fill: '#75695b', fontSize: 11 }} tickLine={false} axisLine={false} />
          <Tooltip labelFormatter={longDay} formatter={(value, key) => [round(value), `${names[Number(key[1])]} ${key[0] === 'a' ? 'actual' : 'projected'}`]}
            contentStyle={{ background: '#fffaf2', border: '1px solid #d6c5a7', borderRadius: 8, fontSize: 12 }} />
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

function OddsTrend({ history }) {
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

function MatchupCard({ matchup }) {
  const [open, setOpen] = useState(false);
  const teams = [matchup.home, matchup.away];
  if (matchup.unavailable) {
    return (
      <article className="fx-card fx-card--empty">
        <p>{teams[0].name} vs {teams[1].name}</p>
        <small>Not available</small>
      </article>
    );
  }
  const odds = [matchup.chance, 100 - matchup.chance];
  const fav = favorite(matchup);
  return (
    <article className="fx-card">
      {teams.map((team, side) => (
        <div className={`fx-team${fav === side ? ' fx-team--fav' : ''}`} key={side}>
          <i style={{ background: COLORS[side] }} aria-hidden="true" />
          <span className="fx-name">{team.name}</span>
          <b>{round(matchup.scores[side])}</b>
          <span className="fx-odds">{pct(odds[side])}</span>
        </div>
      ))}
      <div className="fx-bar" aria-hidden="true">
        {odds.map((value, side) => <i key={side} style={{ flex: `${value} 0 0`, background: COLORS[side], opacity: fav === side ? 1 : 0.35 }} />)}
      </div>
      <ScorePath matchup={matchup} />
      <div className="fx-meta">
        <span>Projected {round(matchup.projected_totals[0])}–{round(matchup.projected_totals[1])}</span>
        <OddsTrend history={matchup.odds_history} />
      </div>
      <button type="button" className="fx-toggle" aria-expanded={open} aria-label={`${open ? 'Hide days' : 'By day'}: ${teams[0].name} vs ${teams[1].name}`} onClick={() => setOpen(!open)}>{open ? 'Hide days' : 'By day'}</button>
      {open && (
        <table className="fx-days">
          <thead><tr><th scope="col">Day</th><th scope="col">{teams[0].name}</th><th scope="col">{teams[1].name}</th><th scope="col">Games</th></tr></thead>
          <tbody>
            {matchup.days.map(day => {
              const projected = day.state === 'projected' || (day.state === 'live' && !day.actual);
              const values = projected ? day.expected : day.actual;
              return (
                <tr key={day.date} className={projected ? 'fx-day--projected' : undefined}>
                  <th scope="row">{weekday(day.date)}<small>{projected ? 'proj.' : day.state}</small></th>
                  <td>{round(values?.[0])}</td><td>{round(values?.[1])}</td>
                  <td>{Number.isFinite(day.games?.[0]) ? `${day.games[0]}–${day.games[1]}` : '—'}</td>
                </tr>
              );
            })}
          </tbody>
        </table>
      )}
    </article>
  );
}

class Boundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <p className="fx-status" role="alert">Predictions unavailable.</p> : this.props.children; }
}

function Fantasy() {
  const [state, setState] = useState({ status: 'loading' });
  useEffect(() => {
    const controller = new AbortController();
    let apiUrl = null;
    try { apiUrl = getUrl(); } catch { /* fall back to the interim snapshot */ }
    loadSnapshot(apiUrl, controller.signal)
      .then(data => setState(data ? { status: 'ready', data } : { status: 'empty' }))
      .catch(error => { if (error.name !== 'AbortError') setState({ status: 'error' }); });
    return () => controller.abort();
  }, []);
  const { status, data } = state;
  return (
    <main className="fx-page">
      <header className="fx-header">
        <Link to="/" className="fx-home">Cozy Commons</Link>
        <h1>Fantasy basketball</h1>
        {data && <p>Matchup {data.matchup.id} · ends {longDay(data.matchup.ends)} · updated {new Date(data.generated_at).toLocaleDateString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' })}</p>}
      </header>
      {status === 'loading' && <p className="fx-status" role="status">Loading…</p>}
      {status === 'empty' && <p className="fx-status">No predictions yet.</p>}
      {status === 'error' && <p className="fx-status" role="alert">Predictions unavailable.</p>}
      {data && (
        <>
          <div className="fx-legend"><span><i className="fx-solid" aria-hidden="true" />Actual</span><span><i className="fx-dash" aria-hidden="true" />Projected</span><span>% = win chance</span></div>
          <div className="fx-grid">{orderMatchups(data.matchups).map((matchup, i) => <MatchupCard key={`${matchup.home.name}-${i}`} matchup={matchup} />)}</div>
          <p className="fx-note">{data.label}</p>
        </>
      )}
    </main>
  );
}

export default function FantasyPage() {
  return <Boundary><Fantasy /></Boundary>;
}
