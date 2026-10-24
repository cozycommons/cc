import React, { useEffect, useState } from 'react';
import { Link, Route, Routes } from 'react-router-dom';
import { getUrl } from '../api.js';
import { loadSnapshot } from './source.js';
import { favorite, orderMatchups } from './paths.js';
import MatchupPage from './MatchupPage.jsx';
import SeasonRace from './SeasonRace.jsx';
import ClaimPanel from './ClaimPanel.jsx';
import { fetchOwners } from './claims.js';
import { weekStory } from './analysis.js';
import { COLORS, Manager, OddsTrend, OwnersContext, ScorePath, TeamLogo, longDay, pct, round, useNarrow } from './parts.jsx';
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
  return (
    <Link className="fx-card fx-card--link" to={matchup.key} aria-label={`${teams[0].name} vs ${teams[1].name}: open matchup`}>
      {teams.map((team, side) => (
        <div className={`fx-team${fav === side ? ' fx-team--fav' : ''}`} key={side}>
          <TeamLogo team={team} side={side} />
          <span className="fx-name"><span>{team.name}</span><small><Manager team={team} />proj. {round(matchup.projected_totals[side])}</small></span>
          <b>{round(matchup.scores[side])}</b>
          <span className="fx-odds">{pct(odds[side])}</span>
        </div>
      ))}
      <div className="fx-bar" aria-hidden="true">
        {odds.map((value, side) => <i key={side} style={{ flex: `${value} 0 0`, background: COLORS[side], opacity: fav === side ? 1 : 0.35 }} />)}
      </div>
      {!narrow && <ScorePath matchup={matchup} height={120} />}
      <div className="fx-meta"><OddsTrend history={matchup.odds_history} name={teams[0].name} /></div>
    </Link>
  );
}

function Hub({ data, apiUrl, onOwnersChange }) {
  const narrow = useNarrow();
  return (
    <>
      {data.season && <SeasonRace season={data.season} narrow={narrow} />}
      <ClaimPanel apiUrl={data.linkable ? apiUrl : null} data={data} onChange={onOwnersChange} />
      <section aria-label="This week's matchups">
        <div className="fx-section-head">
          <h2>This week</h2>
          <span>Ends {longDay(data.matchup.ends)}</span>
        </div>
        {weekStory(data.matchups) && <p className="fx-story">{weekStory(data.matchups)}</p>}
        <div className="fx-grid">{orderMatchups(data.matchups).map(matchup => <MatchupCard key={matchup.key} matchup={matchup} narrow={narrow} />)}</div>
      </section>
    </>
  );
}

function Fantasy() {
  const [state, setState] = useState({ status: 'loading' });
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
  const { status, data } = state;
  const reloadOwners = () => fetchOwners(apiUrl, data?.year, undefined, true).then(setOwners);
  return (
    <main className="fx-page">
      <header className="fx-header">
        <Link to="/" className="fx-home">Cozy Commons</Link>
        <h1><Link to="/fantasy">Fantasy basketball</Link></h1>
        {data && <p>Matchup {data.matchup.id} · updated {new Date(data.generatedAt).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' })}</p>}
      </header>
      {status === 'loading' && <p className="fx-status" role="status">Loading…</p>}
      {status === 'empty' && <p className="fx-status">No predictions yet.</p>}
      {status === 'error' && <p className="fx-status" role="alert">Predictions unavailable.</p>}
      {data && (
        <>
          <OwnersContext.Provider value={owners}>
            <Routes>
              <Route index element={<Hub data={data} apiUrl={apiUrl} onOwnersChange={reloadOwners} />} />
              <Route path=":key" element={<MatchupPage data={data} />} />
            </Routes>
          </OwnersContext.Provider>
          <p className="fx-note">{data.label}</p>
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
