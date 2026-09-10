import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { diceApi } from '../api.js';
import RankedChoice from '../components/RankedChoice.jsx';
import LiveRosterPicker from './LiveRosterPicker.jsx';

const label = (value) => String(value || '').replaceAll('_', ' ');
const shortId = (value) => {
  const text = String(value || '');
  return text.split('-').length === 5 ? text.slice(-4) : text.split('-')[0];
};

const pendingCreateKey = (userId) => `dice:live:create:${userId || 'unknown'}`;
const CREATE_RECOVERY_WINDOW_MS = 5 * 60 * 1000;

function readPendingCreate(userId) {
  try {
    const pending = JSON.parse(window.sessionStorage.getItem(pendingCreateKey(userId))) || null;
    if (!pending?.createdAt || Date.now() - pending.createdAt > CREATE_RECOVERY_WINDOW_MS) {
      window.sessionStorage.removeItem(pendingCreateKey(userId));
      return null;
    }
    return pending;
  } catch {
    return null;
  }
}

function writePendingCreate(userId, attempt) {
  try { window.sessionStorage.setItem(pendingCreateKey(userId), JSON.stringify(attempt)); } catch { /* storage unavailable */ }
}

function clearPendingCreate(userId) {
  try { window.sessionStorage.removeItem(pendingCreateKey(userId)); } catch { /* storage unavailable */ }
}

const DEFAULT_RULES = {
  contract_version: 1,
  ruleset_version: 1,
  scoring_version: 1,
  target_score: 5,
  win_by: 1,
  call_policy: {
    low_call_deadline: 'before_surface_contact',
    low_call_exceptions: [],
    short_boundary: 'center_line_is_short',
    midline_remedy: 'consume_attempt',
    dispute_authority: 'teams_or_designated_referee',
    uncertain_call_remedy: 'retoss',
  },
};

export default function LiveLobby({ auth }) {
  const navigate = useNavigate();
  const [games, setGames] = useState(null);
  const [error, setError] = useState('');
  const [changing, setChanging] = useState('');
  const [profiles, setProfiles] = useState([]);
  const [profilesLoading, setProfilesLoading] = useState(false);
  const [profilesError, setProfilesError] = useState('');
  const [creating, setCreating] = useState(false);
  const [showCreate, setShowCreate] = useState(false);
  const [createError, setCreateError] = useState('');
  const [players, setPlayers] = useState(['', '', '', '']);
  const [ranked, setRanked] = useState(true);
  const createAttempt = useRef(null);

  const load = useCallback(async () => {
    if (!auth.token) return;
    setError('');
    try {
      const loaded = await diceApi.getLiveGames(auth.token);
      setGames(loaded);
      const pending = readPendingCreate(auth.user?.id);
      if (pending && loaded.some((game) => game.id === pending.key)) {
        createAttempt.current = null;
        clearPendingCreate(auth.user?.id);
      }
    } catch (requestError) {
      setError(requestError.message || 'Could not load live games.');
    }
  }, [auth.token, auth.user?.id]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!auth.token) return undefined;
    const timer = window.setInterval(() => load(), 15000);
    return () => window.clearInterval(timer);
  }, [auth.token, load]);

  const loadProfiles = useCallback(async () => {
    if (typeof diceApi.searchProfiles !== 'function') {
      setProfiles([]);
      setProfilesError('Player list is unavailable in this environment.');
      setProfilesLoading(false);
      return;
    }
    setProfilesLoading(true);
    setProfilesError('');
    try {
      const result = await diceApi.searchProfiles('', 500);
      setProfiles(result || []);
    } catch (requestError) {
      setProfiles([]);
      setProfilesError(requestError.message || 'Could not load registered players.');
    } finally {
      setProfilesLoading(false);
    }
  }, []);

  useEffect(() => {
    loadProfiles();
  }, [loadProfiles]);

  const changeMembership = async (game, joined, openAfterJoin = false) => {
    setChanging(game.id);
    setError('');
    try {
      const method = joined ? 'leaveLiveGame' : 'joinLiveGame';
      await diceApi[method](auth.token, game.id);
      if (openAfterJoin) navigate(`/dice/live/${game.id}`);
      else await load();
    } catch (requestError) {
      setError(requestError.message || 'Could not update referee access.');
    } finally {
      setChanging('');
    }
  };

  const createGame = async (event) => {
    event.preventDefault();
    setCreateError('');
    if (players.some((player) => !player) || new Set(players).size !== 4) {
      setCreateError('Choose four distinct registered players.');
      return;
    }
    setCreating(true);
    try {
      const payload = {
        team_order: ['blue', 'clay'],
        teams: { blue: players.slice(0, 2), clay: players.slice(2) },
        rules_snapshot: DEFAULT_RULES,
        ranked,
      };
      const signature = JSON.stringify(payload);
      const pending = readPendingCreate(auth.user?.id);
      createAttempt.current = pending;
      if (pending?.signature === signature && typeof pending.key === 'string') {
        createAttempt.current = pending;
      } else {
        createAttempt.current = { signature, key: crypto.randomUUID(), createdAt: Date.now() };
        writePendingCreate(auth.user?.id, createAttempt.current);
      }
      const created = await diceApi.createLiveGame(auth.token, payload, createAttempt.current.key);
      createAttempt.current = null;
      clearPendingCreate(auth.user?.id);
      navigate(`/dice/live/${created.id}`);
    } catch (requestError) {
      setCreateError(requestError.message || 'Could not start the live game.');
    } finally {
      setCreating(false);
    }
  };

  return (
    <main className="max-w-xl mx-auto px-4 pt-7 pb-24">
      <div className="flex items-end justify-between gap-4 mb-5">
        <div>
          <h1 className="jk-display text-4xl">Live games</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>Join a game and keep score.</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => setShowCreate((current) => {
          if (current) {
            createAttempt.current = null;
            clearPendingCreate(auth.user?.id);
          }
          return !current;
        })}>{showCreate ? 'Cancel' : 'Start game'}</Button>
      </div>

      {showCreate && <form className="jk-card p-5 mb-6" onSubmit={createGame}>
        <p className="jk-label">START 2V2</p>
        <h2 className="jk-display text-2xl mt-2">Pick two teams</h2>
        {profilesLoading && <p className="mt-3 text-sm" role="status" style={{ color: 'var(--text-secondary)' }}>Loading registered players…</p>}
        {profilesError && <div className="mt-3 flex items-center justify-between gap-3 text-sm" role="alert" style={{ color: 'var(--state-danger)' }}><span>{profilesError}</span><Button type="button" size="sm" variant="outline" onClick={loadProfiles}>Retry</Button></div>}
        <LiveRosterPicker profiles={profiles} players={players} onChange={setPlayers} />
        <div className="mt-7 pt-6" style={{ borderTop: '1px solid var(--border-subtle)' }}>
          <RankedChoice ranked={ranked} onChange={setRanked} />
        </div>
        {createError && <p role="alert" className="mt-3 text-sm" style={{ color: 'var(--state-danger)' }}>{createError}</p>}
        <Button className="w-full min-h-12 mt-6" disabled={creating || profilesLoading || Boolean(profilesError) || players.some((player) => !player) || new Set(players).size !== 4}>{profilesLoading ? 'Loading players…' : creating ? 'Starting…' : 'Start live game'}</Button>
      </form>}

      {error && games !== null && (
        <div className="mb-4 flex items-center justify-between gap-3 text-xs" role="status" style={{ color: 'var(--text-secondary)' }}>
          <span>Showing the last update.</span>
          <button type="button" className="underline" onClick={load}>Try again</button>
        </div>
      )}
      {games === null && !error && <p className="jk-label py-8 text-center">Loading live games…</p>}
      {games === null && error && (
        <div className="jk-card p-6 text-center" role="alert">
          <h2 className="jk-display text-2xl">Couldn’t load live games</h2>
          <Button className="mt-4" variant="outline" onClick={load}>Try again</Button>
        </div>
      )}
      {games?.length === 0 && (
        <div className="jk-card p-6 text-center">
          <h2 className="jk-display text-2xl">No games on the roof</h2>
          <p className="mt-2 text-sm" style={{ color: 'var(--text-secondary)' }}>Ongoing 2v2 games will appear here.</p>
        </div>
      )}

      <div className="space-y-3">
        {games?.map((game) => {
          const joinedRefs = game.referees.filter((referee) => !referee.left_at);
          const joined = joinedRefs.some((referee) => referee.user_id === auth.user?.id);
          const [left, right] = game.team_order;
          const playerLabel = (playerId) => game.player_names?.[playerId] || shortId(playerId);
          return (
            <article key={game.id} className="jk-card p-4">
              <div className="flex justify-between gap-3">
                <span className="jk-label">{game.status === 'active' ? 'Live' : label(game.status)}</span>
              </div>
              <Link to={`/dice/live/${game.id}`} className="block mt-3" aria-label={`Open live game ${shortId(game.id)}`}>
                <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3">
                  <p className="font-semibold min-w-0 break-words">{game.teams[left].map(playerLabel).join(' + ')}</p>
                  <p className="jk-display text-4xl tabular-nums">{game.score[0]}–{game.score[1]}</p>
                  <p className="font-semibold text-right min-w-0 break-words">{game.teams[right].map(playerLabel).join(' + ')}</p>
                </div>
              </Link>
              <div className="flex items-center justify-between gap-3 mt-4 pt-3" style={{ borderTop: '1px solid var(--border-subtle)' }}>
                <p className="text-xs" style={{ color: 'var(--text-tertiary)' }}>
                  {joinedRefs.length} referee{joinedRefs.length === 1 ? '' : 's'} joined
                </p>
                {joined ? (
                  <div className="flex items-center gap-2">
                    <Link className="px-3 py-2 rounded-md text-sm font-semibold" style={{ background: 'var(--surface-strong)', color: 'var(--text-on-strong)' }} to={`/dice/live/${game.id}`}>Referee</Link>
                    <Button size="sm" variant="ghost" disabled={changing === game.id} onClick={() => changeMembership(game, true)}>
                      {changing === game.id ? 'Leaving…' : 'Leave'}
                    </Button>
                  </div>
                ) : (
                  <Button size="sm" disabled={changing === game.id} onClick={() => changeMembership(game, false, true)}>
                    {changing === game.id ? 'Joining…' : 'Join & referee'}
                  </Button>
                )}
              </div>
            </article>
          );
        })}
      </div>
    </main>
  );
}
