import React, { useContext, useEffect, useRef, useState } from 'react';
import { Link, Route, Routes } from 'react-router-dom';
import SiteHeader from '../components/SiteHeader.jsx';
import { getUrl } from '../api.js';
import { cachedSnapshot, loadSnapshot } from './source.js';
import { favorite, orderMatchups } from './paths.js';
import MatchupPage from './MatchupPage.jsx';
import SeasonRace from './SeasonRace.jsx';
import ClaimPanel from './ClaimPanel.jsx';
import { fetchOwners, leagueLinks } from './claims.js';
import { acquiredLabel, finished, highlights, matchupRead } from './analysis.js';
import { Manager, OwnersContext, TeamLogo, WinChart, round, useNarrow, weekday, winPct } from './parts.jsx';
import { LeagueLinksContext, MatchupLink, PlayerLink, TeamLinks } from './EspnLink.jsx';
import { checkAdmin } from './admin.js';
import FantasyAdmin from './FantasyAdmin.jsx';
import { AdminEntry } from './AdminPanel.jsx';
import Basketball from './Basketball.jsx';
import { Confetti, MotionLink, GameStatus, OddsBar, Score, sharedName } from './motion.jsx';
import '../../../design/cozy-wabi/components.css';
import './fantasy.css';

function MatchupCard({ matchup, week, mine }) {
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
    <MotionLink className={`fx-card fx-card--link${mine ? ' fx-mine' : ''}`} to={matchup.key} aria-label={`${teams[0].name} vs ${teams[1].name}: open matchup`}>
      {teams.map((team, side) => (
        <div className={`fx-team${fav === side ? ' fx-team--fav' : ''}`} key={side}>
          <span style={{ viewTransitionName: sharedName(matchup, side, 'jersey') }}><TeamLogo team={team} side={side} /></span>
          <span className="fx-name"><span>{team.name}</span><small><Manager team={team} />proj. {round(matchup.projected_totals[side])}</small></span>
          <b><Score value={matchup.scores[side]} side={side} name={sharedName(matchup, side, 'score')} /><Confetti matchup={matchup} side={side} week={week} /></b>
          <span className="fx-odds">{winPct(odds[side], finished(matchup))}</span>
        </div>
      ))}
      <OddsBar chance={matchup.chance} />
      <p className="fx-why"><GameStatus matchup={matchup} /><span>{read.facts.join(' · ')}</span></p>
      <WinChart history={matchup.odds_history} final={finished(matchup)} />
    </MotionLink>
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
        {rows.map((row, index) => {
          const how = acquiredLabel(row.acquired);
          return (
            <li key={`${row.key}-${row.id}`}>
              <div className="fx-hl-card">
                <img src={headshot(row.id)} alt="" loading="lazy" referrerPolicy="no-referrer"
                  onError={event => { event.currentTarget.hidden = true; event.currentTarget.parentElement.classList.add('fx-hl-no-photo'); }} />
                <span className="fx-hl-main">
                  <b>{index === 0 && <span className="fx-flame" aria-label="Top outperformer">🔥</span>}<PlayerLink id={row.id} name={row.name} badge /></b>
                  <small><TeamLogo team={row.team} side={row.side} size={16} /><Link to={row.key}>{row.team.name}</Link><Manager team={row.team} /></small>
                  {how && <span className="fx-hl-how">{how}</span>}
                </span>
                <span className="fx-hl-num">
                  <strong>+{round(row.diff)}</strong>
                  <small>{round(row.actual)} pts{row.games > 1 ? ` · ${row.games} games` : ''}</small>
                </span>
              </div>
            </li>
          );
        })}
      </ul>
    </section>
  );
}

function SkeletonCard({ failed }) {
  return <article className={`fx-card fx-skeleton${failed ? ' fx-skeleton--failed' : ''}`} aria-hidden="true">{[0, 1].map(side => <div className="fx-team" key={side}><span className="fx-logo" /><span className="fx-name"><span className="fx-bone" /><small className="fx-bone">&nbsp;</small></span><b>—</b><span>—</span></div>)}<div className="fx-bar fx-bone" /><p className="fx-why fx-bone">&nbsp;</p></article>;
}

function Loading({ received, total }) {
  return <div className="fx-loading" role="status">
    <span className="fx-loading-ball"><Basketball size={22} /></span>
    <span>{total ? `${received} of ${total}` : 'Loading'}</span>
  </div>;
}

function Hub({ data, apiUrl, onOwnersChange, progress, loading }) {
  const links = useContext(LeagueLinksContext);
  const narrow = useNarrow();
  const matchups = data?.matchups || [];
  const ordered = progress?.meta?.slots || (data ? orderMatchups(matchups) : Array.from({ length: 6 }, (_, key) => ({ key })));
  // The viewer's own matchup leads.
  const isMine = slot => links?.team_id != null && [slot.home?.id ?? slot.home, slot.away?.id ?? slot.away].includes(links.team_id);
  const slots = [...ordered.filter(isMine), ...ordered.filter(slot => !isMine(slot))];
  const ready = new Map(matchups.map(matchup => [matchup.key, matchup]));
  const total = progress?.meta?.totalMatchups;
  return <div className="fx-hub">
    <section id="fx-week" className="fx-slot fx-slot--week" aria-label="This week's matchups" aria-busy={loading}>
      <div className="fx-section-head"><h2>This week</h2><span>{data ? `Ends ${weekday(data.matchup.ends)}` : '\u00a0'}</span>
        {loading && <Loading received={progress?.matchups.length || 0} total={total} />}
      </div>
      <div className="fx-grid">{slots.map((slot, index) => {
        const matchup = ready.get(slot.key);
        const mine = matchup && isMine(matchup);
        return <div className="fx-matchup-card" key={slot.key}>{matchup ? <div className="fx-arrive" style={{ '--i': index }}><MatchupCard matchup={matchup} mine={mine} week={`${data.year}-${data.matchup.id}`} /><div className="fx-card-links"><MatchupLink matchup={matchup} />{mine && <TeamLinks teamId={links.team_id} />}</div></div> : <SkeletonCard failed={!loading} />}</div>;
      })}</div>
      <Highlights rows={highlights(matchups)} />
    </section>
    {data?.season && <div id="fx-race" className="fx-slot"><SeasonRace season={data.season} narrow={narrow} /></div>}
    {data && <div id="fx-team" className="fx-slot"><ClaimPanel apiUrl={data.linkable ? apiUrl : null} data={data} onChange={onOwnersChange} /></div>}
  </div>;
}

function Fantasy() {
  useEffect(() => {
    const previous = document.title;
    document.title = 'Fantasy Nelsoners · Cozy Commons';
    return () => { document.title = previous; };
  }, []);
  const [apiUrl] = useState(() => { try { return getUrl(); } catch { return null; } });
  const [state, setState] = useState(() => {
    const data = cachedSnapshot(apiUrl);
    return data ? { status: 'ready', data } : { status: 'loading' };
  });
  const saved = useRef(state.data);
  const [attempt, setAttempt] = useState(0);
  const [links, setLinks] = useState(null);
  const [adminToken, setAdminToken] = useState(null);
  const [adminOpen, setAdminOpen] = useState(false);
  const adminEntry = useRef(null);
  const [viewer, setViewer] = useState(null);
  const [revision, setRevision] = useState(0);
  const [owners, setOwners] = useState(() => new Map());
  useEffect(() => {
    const controller = new AbortController();
    loadSnapshot(apiUrl, controller.signal, progress => {
      if (controller.signal.aborted || progress.error) return;
      setState(previous => ({
        status: progress.done ? 'ready' : 'loading',
        data: progress.meta ? { ...progress.meta, matchups: [...(saved.current?.matchups || []).filter(old => !progress.matchups.some(next => next.key === old.key)), ...progress.matchups] } : previous.data,
        progress,
      }));
    })
      .then(data => {
        setState(previous => data ? { status: 'ready', data, progress: previous.progress } : previous.data ? { ...previous, status: 'ready' } : { status: 'empty' });
        if (data?.linkable) fetchOwners(apiUrl, data.year, controller.signal).then(setOwners);
      })
      .catch(error => { if (error.name !== 'AbortError') setState(previous => saved.current ? { status: 'ready', data: saved.current } : { ...previous, status: 'error' }); });
    return () => controller.abort();
  }, [apiUrl, attempt]);
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
      import('./auth.js').then(async ({ auth }) => {
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
  const { status, data, progress } = state;
  const reloadOwners = () => {
    setLinks(null);
    setRevision(value => value + 1);
    return fetchOwners(apiUrl, data?.year, undefined, true).then(setOwners);
  };
  useEffect(() => { setAdminOpen(false); }, [adminToken]);
  const closeAdmin = () => { setAdminOpen(false); adminEntry.current?.focus(); };
  return (
    <div className="fx-page">
      <SiteHeader product="Fantasy" to="/fantasy" icon={<Basketball />}>
        {adminToken && <AdminEntry ref={adminEntry} open={adminOpen} onClick={() => adminOpen ? closeAdmin() : setAdminOpen(true)} />}
      </SiteHeader>
      {adminToken && adminOpen && <FantasyAdmin key={adminToken} apiUrl={apiUrl} token={adminToken} initialSeason={data?.year}
        onSaved={() => setRevision(value => value + 1)} onClose={closeAdmin} />}
      <main className="fx-main">
        <div className="fx-header">
          <h1>Fantasy Nelsoners</h1>
          <p>{data ? `Week ${data.matchup.id} · Scores as of ${new Date(data.capturedAt).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' })}` : '\u00a0'}</p>
        {status === 'loading' && <div className="fx-progress" role="progressbar" aria-label="Matchups received" aria-valuemin={0} aria-valuemax={progress?.meta?.totalMatchups || 6} aria-valuenow={(progress?.matchups.length || 0)}><i style={{ transform: `scaleX(${(progress?.matchups.length || 0) / (progress?.meta?.totalMatchups || 6)})` }} /></div>}
        </div>

        {status === 'empty' && <p className="fx-status">No predictions yet.</p>}
        {status === 'error' && <div className="fx-status" role="alert"><p>Shot clock ran out.</p><button className="cc-button" onClick={() => { setState({ status: 'loading' }); setAttempt(value => value + 1); }}>Try again</button></div>}
        {(data || status === 'loading') && (
          <>
            <OwnersContext.Provider value={owners}><LeagueLinksContext.Provider value={links?.season === data?.year ? links : null}>
              <Routes>
                <Route index element={<Hub data={data} apiUrl={apiUrl} onOwnersChange={reloadOwners} progress={progress} loading={status === 'loading'} />} />
                <Route path=":key" element={data ? <MatchupPage data={data} /> : <Hub apiUrl={apiUrl} loading />} />
              </Routes>
            </LeagueLinksContext.Provider></OwnersContext.Provider>
          </>
        )}
      </main>
    </div>
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
