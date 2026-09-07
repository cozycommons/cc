import React, { useCallback, useEffect, useState } from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { diceApi } from '../api.js';
import LiveRosterPicker from './LiveRosterPicker.jsx';

const label = (value) => String(value || '').replaceAll('_', ' ');
const shortId = (value) => {
  const text = String(value || '');
  return text.split('-').length === 5 ? text.slice(-4) : text.split('-')[0];
};

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
  const enabled = auth.features?.dice_live_referee?.effective === true;
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

  const load = useCallback(async () => {
    if (!enabled || !auth.token) return;
    setError('');
    try {
      setGames(await diceApi.getLiveGames(auth.token));
    } catch (requestError) {
      setError(requestError.message || 'Could not load live games.');
    }
  }, [auth.token, enabled]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!enabled || !auth.token) return undefined;
    const timer = window.setInterval(() => load(), 15000);
    return () => window.clearInterval(timer);
  }, [auth.token, enabled, load]);

  const loadProfiles = useCallback(async () => {
    if (!enabled || typeof diceApi.searchProfiles !== 'function') {
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
  }, [enabled]);

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
      const created = await diceApi.createLiveGame(auth.token, {
        team_order: ['blue', 'clay'],
        teams: { blue: players.slice(0, 2), clay: players.slice(2) },
        rules_snapshot: DEFAULT_RULES,
      });
      navigate(`/dice/live/${created.id}`);
    } catch (requestError) {
      setCreateError(requestError.message || 'Could not start the live game.');
    } finally {
      setCreating(false);
    }
  };

  if (!enabled) {
    return (
      <main className="max-w-xl mx-auto px-4 py-12">
        <div className="jk-card p-6 text-center">
          <p className="jk-label mb-2">// LIVE REFEREE</p>
          <h1 className="jk-display text-3xl">Live referee unavailable</h1>
          <p className="mt-3 text-sm" style={{ color: 'var(--text-secondary)' }}>
            This private beta is not enabled for your account.
          </p>
          <Link to="/dice" className="inline-block mt-5 underline">Back to Dice</Link>
        </div>
      </main>
    );
  }

  return (
    <main className="max-w-xl mx-auto px-4 pt-7 pb-24">
      <div className="flex items-end justify-between gap-4 mb-5">
        <div>
          <h1 className="jk-display text-4xl">Live games</h1>
          <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>Join a game and keep score.</p>
        </div>
        <Button variant="outline" size="sm" onClick={() => setShowCreate((current) => !current)}>{showCreate ? 'Cancel' : 'Start game'}</Button>
      </div>

      {showCreate && <form className="jk-card p-4 mb-5" onSubmit={createGame}>
        <p className="jk-label">START 2V2</p>
        <p className="text-sm mt-2" style={{ color: 'var(--text-secondary)' }}>Pick two teams.</p>
        {profilesLoading && <p className="mt-3 text-sm" role="status" style={{ color: 'var(--text-secondary)' }}>Loading registered players…</p>}
        {profilesError && <div className="mt-3 flex items-center justify-between gap-3 text-sm" role="alert" style={{ color: 'var(--state-danger)' }}><span>{profilesError}</span><Button type="button" size="sm" variant="outline" onClick={loadProfiles}>Retry</Button></div>}
        <LiveRosterPicker profiles={profiles} players={players} onChange={setPlayers} />
        {createError && <p role="alert" className="mt-3 text-sm" style={{ color: 'var(--state-danger)' }}>{createError}</p>}
        <Button className="w-full min-h-12 mt-4" disabled={creating || profilesLoading || Boolean(profilesError) || players.some((player) => !player) || new Set(players).size !== 4}>{profilesLoading ? 'Loading players…' : creating ? 'Starting…' : 'Start live game'}</Button>
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
