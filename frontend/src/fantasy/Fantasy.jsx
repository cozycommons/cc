import React, { useEffect, useState } from 'react';
import { Link, Route, Routes } from 'react-router-dom';
import { getUrl } from '../api.js';
import { loadSnapshot } from './source.js';
import { favorite, orderMatchups } from './paths.js';
import MatchupPage from './MatchupPage.jsx';
import SeasonRace from './SeasonRace.jsx';
import ClaimPanel from './ClaimPanel.jsx';
import OnboardPanel from './OnboardPanel.jsx';
import { fetchOwners, leagueLinks } from './claims.js';
import { acquiredLabel, finished, highlights, matchupRead } from './analysis.js';
import { COLORS, Manager, OddsTrend, OwnersContext, ScorePath, TeamLogo, longDay, round, useNarrow, winPct } from './parts.jsx';
import { LeagueLinksContext, MatchupLink, PlayerLink } from './EspnLink.jsx';
import { checkAdmin } from './admin.js';
import FantasyAdmin from './FantasyAdmin.jsx';
import './fantasy.css';

function MatchupCard({ matchup, narrow }) {
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
  const read = matchupRead(matchup);
  return (
    <Link className="fx-card fx-card--link" to={matchup.key} aria-label={`${teams[0].name} vs ${teams[1].name}: open matchup`}>
      <div className="fx-team fx-card-head" aria-hidden="true"><span /><span /><small>Score</small><small>To win</small></div>
      {teams.map((team, side) => (
        <div className={`fx-team${fav === side ? ' fx-team--fav' : ''}`} key={side}>
          <TeamLogo team={team} side={side} />
          <span className="fx-name"><span>{team.name}</span><small><Manager team={team} />proj. {round(matchup.projected_totals[side])}</small></span>
          <b>{round(matchup.scores[side])}</b>
          <span className="fx-odds">{winPct(odds[side], finished(matchup))}</span>
        </div>
      ))}
      <div className="fx-bar" aria-hidden="true">
        {odds.map((value, side) => <i key={side} style={{ flex: `${value} 0 0`, background: COLORS[side], opacity: fav === side ? 1 : 0.35 }} />)}
      </div>
      <p className="fx-why" style={{ color: read.side == null ? undefined : COLORS[read.side] }}>{read.facts.join(' · ')}</p>
      {!narrow && <ScorePath matchup={matchup} height={120} />}
      <div className="fx-meta"><OddsTrend history={matchup.odds_history} name={teams[0].name} final={finished(matchup)} /></div>
    </Link>
  );
}

const headshot = id => `https://a.espncdn.com/i/headshots/nba/players/full/${id}.png`;

// This week's biggest outperformers, with how their manager got them.
function Highlights({ rows }) {
  if (!rows.length) return null;
  return (
    <section className="fx-highlights" aria-label="Outperformers this week">
      <h3>Outperformers</h3>
      <ul>
        {rows.map(row => {
          const how = acquiredLabel(row.acquired);
          return (
            <li key={`${row.key}-${row.id}`}>
              <div className="fx-hl-card">
                <img src={headshot(row.id)} alt="" loading="lazy" referrerPolicy="no-referrer"
                  onError={event => { event.currentTarget.style.visibility = 'hidden'; }} />
                <span className="fx-hl-main">
                  <b><PlayerLink id={row.id} name={row.name} /></b>
                  <small><TeamLogo team={row.team} side={row.side} size={16} /><Link to={row.key}>{row.team.name}</Link></small>
                  {how && <span className="fx-hl-how">{how}</span>}
                </span>
                <span className="fx-hl-num">
                  <strong>+{round(row.diff)}</strong>
                  <small>{round(row.actual)} vs {round(row.expected)} exp.{row.games > 1 ? ` · ${row.games} games` : ''}</small>
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

// Phones: one row of jump tabs, and this week's matchups come first.
const HUB_TABS = [['fx-week', 'This week'], ['fx-race', 'Playoff race'], ['fx-team', 'Your team'], ['fx-lineups', 'Lineups']];

// Only sections that actually render get a tab, so no tab jumps to an empty spot.
export function HubTabs({ show }) {
  const jump = id => document.getElementById(id)?.scrollIntoView({ behavior: 'smooth', block: 'start' });
  return (
    <nav className="fx-tabs" aria-label="Sections">
      {HUB_TABS.filter(([id]) => show[id]).map(([id, label]) => (
        <button key={id} type="button" onClick={() => jump(id)}>{label}</button>
      ))}
    </nav>
  );
}

function Hub({ data, apiUrl, onOwnersChange }) {
  const narrow = useNarrow();
  const outperformers = <Highlights rows={highlights(data.matchups)} />;
  const week = (
    <section id="fx-week" className="fx-slot fx-slot--week" aria-label="This week's matchups">
      <div className="fx-section-head">
        <h2>This week</h2>
        <span>Ends {longDay(data.matchup.ends)}</span>
      </div>
      {!narrow && outperformers}
      <div className="fx-grid">{orderMatchups(data.matchups).map(matchup => (
        <div className="fx-matchup-card" key={matchup.key}>
          <MatchupCard matchup={matchup} narrow={narrow} />
          <MatchupLink matchup={matchup} />
        </div>
      ))}</div>
      {narrow && outperformers}
    </section>
  );
  // Phones lead with this week's score cards; render order (not CSS order) so reading order matches.
  return (
    <div className="fx-hub">
      {narrow && <HubTabs show={{ 'fx-week': true, 'fx-race': !!data.season, 'fx-team': !!(data.linkable && apiUrl), 'fx-lineups': !!apiUrl }} />}
      {narrow && week}
      {data.season && <div id="fx-race" className="fx-slot"><SeasonRace season={data.season} narrow={narrow} /></div>}
      <div id="fx-team" className="fx-slot"><ClaimPanel apiUrl={data.linkable ? apiUrl : null} data={data} onChange={onOwnersChange} /></div>
      <div id="fx-lineups" className="fx-slot"><OnboardPanel apiUrl={apiUrl} /></div>
      {!narrow && week}
    </div>
  );
}

function Fantasy() {
  const [state, setState] = useState({ status: 'loading' });
  const [links, setLinks] = useState(null);
  const [adminToken, setAdminToken] = useState(null);
  const [viewer, setViewer] = useState(null);
  const [revision, setRevision] = useState(0);
  const [owners, setOwners] = useState(() => new Map());
  const [apiUrl] = useState(() => { try { return getUrl(); } catch { return null; } });
  useEffect(() => {
    const controller = new AbortController();
    loadSnapshot(apiUrl, controller.signal)
      .then(data => {
        setState(data ? { status: 'ready', data } : { status: 'empty' });
        if (data?.linkable) fetchOwners(apiUrl, data.year, controller.signal).then(setOwners);
      })
      .catch(error => { if (error.name !== 'AbortError') setState({ status: 'error' }); });
    return () => controller.abort();
  }, [apiUrl]);
  useEffect(() => {
    let active = true, generation = 0, subscription;
    const refresh = async (session) => {
      const request = ++generation;
      setLinks(null);
      setAdminToken(null);
      const token = session?.access_token;
      setViewer(token ? { token } : null);
      const admin = token && apiUrl ? await checkAdmin(apiUrl, token).catch(() => null) : null;
      if (active && request === generation) setAdminToken(admin?.is_admin === true ? token : null);
    };
    if (apiUrl) {
      import('../supabase').then(async ({ auth }) => {
        const result = await auth.onAuthStateChange((_event, session) => { refresh(session); });
        subscription = result.data.subscription;
        if (!active) return subscription.unsubscribe();
        const request = generation;
        const session = await auth.getSession();
        if (active && request === generation) refresh(session);
      }).catch(() => {});
    }
    return () => { active = false; subscription?.unsubscribe(); };
  }, [apiUrl]);
  useEffect(() => {
    let active = true;
    setLinks(null);
    if (viewer && apiUrl && state.data?.linkable) {
      leagueLinks(apiUrl, viewer.token).then(next => { if (active) setLinks(next); }).catch(() => {});
    }
    return () => { active = false; };
  }, [apiUrl, viewer, revision, state.data]);
  const { status, data } = state;
  const reloadOwners = () => {
    setLinks(null);
    setRevision(value => value + 1);
    return fetchOwners(apiUrl, data?.year, undefined, true).then(setOwners);
  };
  return (
    <main className="fx-page">
      <header className="fx-header">
        <Link to="/" className="fx-home">Cozy Commons</Link>
        <h1><Link to="/fantasy">Fantasy basketball</Link></h1>
        {data && <p>Matchup {data.matchup.id} · updated {new Date(data.generatedAt).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' })}</p>}
      </header>
      {adminToken && <FantasyAdmin key={adminToken} apiUrl={apiUrl} token={adminToken} initialSeason={data?.year} onSaved={() => setRevision(value => value + 1)} />}
      {status === 'loading' && <p className="fx-status" role="status">Loading…</p>}
      {status === 'empty' && <p className="fx-status">No predictions yet.</p>}
      {status === 'error' && <p className="fx-status" role="alert">Predictions unavailable.</p>}
      {data && (
        <>
          <OwnersContext.Provider value={owners}><LeagueLinksContext.Provider value={links?.season === data.year ? links : null}>
            <Routes>
              <Route index element={<Hub data={data} apiUrl={apiUrl} onOwnersChange={reloadOwners} />} />
              <Route path=":key" element={<MatchupPage data={data} />} />
            </Routes>
          </LeagueLinksContext.Provider></OwnersContext.Provider>
        </>
      )}
    </main>
  );
}

class Boundary extends React.Component {
  state = { failed: false };
  static getDerivedStateFromError() { return { failed: true }; }
  render() { return this.state.failed ? <p className="fx-status" role="alert">Predictions unavailable.</p> : this.props.children; }
}

export default function FantasyPage() {
  return <Boundary><Fantasy /></Boundary>;
}
