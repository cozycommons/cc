import React, { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { diceApi } from '../api.js';
import PlayerPicker from '../components/PlayerPicker.jsx';
import SinkCountInput from '../components/SinkCountInput.jsx';

const emptySlots = { t1p1: null, t1p2: null, t2p1: null, t2p2: null };

export default function LogMatch({ auth, editMode = false }) {
  const { gameId } = useParams();
  const navigate = useNavigate();
  const location = useLocation();
  const { user, token, isAdmin, loading: authLoading } = auth;
  // Set when arriving from a tournament's "Enter Result" button: prefills
  // the players from that scheduled match (plus its 1v1/2v2 format via
  // `matchType`) and, on success, deletes the scheduled match (it's now a
  // real completed game) and returns to the tournament instead of the game
  // detail page.
  // `bracketSlot` is set instead when arriving from a bracket match
  // ("semi1" | "semi2" | "final") — same idea, but on success it records
  // the game against that bracket slot rather than deleting a scheduled
  // match.
  const { tournamentId: navTournamentId, scheduledMatchId, bracketSlot, prefill, matchType: navMatchType } = location.state || {};

  const [profiles, setProfiles] = useState([]);
  const [slots, setSlots] = useState(emptySlots);
  const [selfSinks, setSelfSinks] = useState({});
  const [sinks, setSinks] = useState({});
  const [team1Score, setTeam1Score] = useState('');
  const [team2Score, setTeam2Score] = useState('');
  const [ranked, setRanked] = useState(false);
  const [substituteIds, setSubstituteIds] = useState({});
  const [tournamentId, setTournamentId] = useState(navTournamentId || null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [loadingGame, setLoadingGame] = useState(editMode);
  const createAttemptRef = useRef(null);
  // A scheduled match or bracket slot arrives with its format already
  // fixed via `navMatchType`, so the toggle is hidden there. A manual
  // tournament log (the host's "+ Log Game" button, tournamentId set but
  // no scheduledMatchId/bracketSlot) still lets the logger choose.
  const formatIsFixed = Boolean(scheduledMatchId || bracketSlot);
  const [matchType, setMatchType] = useState(navMatchType || '2v2');
  const isSingles = matchType === '1v1';

  const changeMatchType = (next) => {
    setMatchType(next);
    if (next === '1v1') {
      setSlots((s) => ({ ...s, t1p2: null, t2p2: null }));
    }
  };

  // Fetched once and shared by all 4 pickers below, instead of each one
  // independently hitting the backend.
  useEffect(() => {
    diceApi.searchProfiles('', 100).then(setProfiles).catch(() => setProfiles([]));
  }, []);

  useEffect(() => {
    if (editMode || !prefill || profiles.length === 0) return;
    const find = (uid) => profiles.find((p) => p.user_id === uid) || null;
    setSlots({
      t1p1: find(prefill.t1p1),
      t1p2: find(prefill.t1p2),
      t2p1: find(prefill.t2p1),
      t2p2: find(prefill.t2p2),
    });
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [profiles]);

  useEffect(() => {
    if (!editMode) return;
    diceApi.getGame(gameId).then((game) => {
      const byTeam = (team, idx) => game.players.filter((p) => p.team === team)[idx] || null;
      setSlots({
        t1p1: byTeam(1, 0),
        t1p2: byTeam(1, 1),
        t2p1: byTeam(2, 0),
        t2p2: byTeam(2, 1),
      });
      setMatchType(game.players.length === 2 ? '1v1' : '2v2');
      const selfSinksMap = {};
      const sinksMap = {};
      const substitutes = {};
      game.players.forEach((p) => {
        selfSinksMap[p.user_id] = p.self_sinks;
        sinksMap[p.user_id] = p.sinks;
        if (p.counts_for_group_stage === false) substitutes[p.user_id] = true;
      });
      setSelfSinks(selfSinksMap);
      setSinks(sinksMap);
      setSubstituteIds(substitutes);
      setTeam1Score(String(game.team1_score));
      setTeam2Score(String(game.team2_score));
      setRanked(game.ranked);
      setTournamentId(game.tournament_id || null);
      setLoadingGame(false);
    }).catch(() => setLoadingGame(false));
  }, [editMode, gameId]);

  const activeSlotKeys = isSingles ? ['t1p1', 't2p1'] : ['t1p1', 't1p2', 't2p1', 't2p2'];
  const requiredPlayerCount = activeSlotKeys.length;

  const chosenIds = useMemo(
    () => activeSlotKeys.map((key) => slots[key]).filter(Boolean).map((p) => p.user_id),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [slots, isSingles]
  );

  const allSlotsFilled = activeSlotKeys.every((key) => Boolean(slots[key]));
  const scoresValid = team1Score !== '' && team2Score !== '' && Number(team1Score) !== Number(team2Score);
  const canSubmit = allSlotsFilled && scoresValid && new Set(chosenIds).size === requiredPlayerCount && !submitting;

  const setSlot = (key) => (profile) => setSlots((s) => ({ ...s, [key]: profile }));

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!canSubmit || !token) return;
    setSubmitting(true);
    setError(null);
    try {
      const teamOf = { t1p1: 1, t1p2: 1, t2p1: 2, t2p2: 2 };
      const players = activeSlotKeys.map((key) => ({
        user_id: slots[key].user_id,
        team: teamOf[key],
        self_sinks: selfSinks[slots[key].user_id] || 0,
        sinks: sinks[slots[key].user_id] || 0,
        counts_for_group_stage: !substituteIds[slots[key].user_id],
      }));
      const payload = {
        ranked,
        team1_score: Number(team1Score),
        team2_score: Number(team2Score),
        tournament_id: tournamentId,
        players,
      };
      if (editMode) {
        const updated = await diceApi.updateGame(token, gameId, payload);
        navigate(`/dice/game/${updated.id}`);
      } else {
        const fingerprint = JSON.stringify(payload);
        if (createAttemptRef.current?.fingerprint !== fingerprint) {
          createAttemptRef.current = { fingerprint, key: crypto.randomUUID() };
        }
        const created = await diceApi.createGame(
          token, payload, createAttemptRef.current.key
        );
        createAttemptRef.current = null;
        if (tournamentId && scheduledMatchId) {
          try {
            await diceApi.deleteScheduledMatch(token, tournamentId, scheduledMatchId);
          } catch (err) {
            // Best effort: the game is already logged; a stale scheduled
            // entry left behind isn't worth failing the whole submission.
          }
          navigate(`/dice/tournament/${tournamentId}`);
        } else if (tournamentId && bracketSlot) {
          try {
            await diceApi.resolveBracketMatch(token, tournamentId, bracketSlot, created.id);
          } catch (err) {
            // Best effort: the game is already logged; the bracket just
            // won't advance automatically if this call fails.
          }
          navigate(`/dice/tournament/${tournamentId}`);
        } else {
          navigate(`/dice/game/${created.id}`);
        }
      }
    } catch (err) {
      setError(`Failed to save match. Make sure all ${requiredPlayerCount} players are distinct and scores don't tie.`);
    } finally {
      setSubmitting(false);
    }
  };

  if (authLoading || loadingGame) {
    return <div className="max-w-xl mx-auto px-4 sm:px-6 py-8">Loading…</div>;
  }

  if (!user) {
    return (
      <div className="max-w-xl mx-auto px-4 sm:px-6 py-8">
        <p style={{ color: 'var(--text-secondary)' }}>Sign in to log a match.</p>
      </div>
    );
  }

  return (
    <div className="max-w-xl mx-auto px-4 sm:px-6 py-8">
      <p className="jk-display mb-6" style={{ fontSize: 28 }}>
        {editMode ? 'Edit Match' : tournamentId ? (bracketSlot ? 'Log Bracket Match' : 'Log Tournament Match') : 'Log Match'}
      </p>
      <form onSubmit={handleSubmit} className="jk-card p-6 flex flex-col gap-6">
        {!formatIsFixed && (
          <div>
            <p className="jk-label mb-2">Match Type</p>
            <div className="inline-flex" style={{ border: '1px solid var(--border-default)', borderRadius: 'var(--radius-pill)', overflow: 'hidden' }}>
              {['2v2', '1v1'].map((type) => (
                <button
                  key={type}
                  type="button"
                  onClick={() => changeMatchType(type)}
                  style={{
                    fontFamily: 'var(--font-body)',
                    fontSize: 13,
                    fontWeight: 500,
                    padding: '6px 16px',
                    background: matchType === type ? 'var(--accent-primary)' : 'transparent',
                    color: matchType === type ? '#fff' : 'var(--text-secondary)',
                  }}
                >
                  {type === '2v2' ? '2v2 (Doubles)' : '1v1 (Singles)'}
                </button>
              ))}
            </div>
          </div>
        )}

        <div>
          <p className="jk-label mb-2" style={{ color: 'var(--team1-color)' }}>Team 1</p>
          <div className={isSingles ? 'grid grid-cols-1 gap-3' : 'grid grid-cols-2 gap-3'}>
            <PlayerPicker label={isSingles ? 'Player' : 'Player 1'} profiles={profiles} value={slots.t1p1} onChange={setSlot('t1p1')} excludeIds={chosenIds} />
            {!isSingles && (
              <PlayerPicker label="Player 2" profiles={profiles} value={slots.t1p2} onChange={setSlot('t1p2')} excludeIds={chosenIds} />
            )}
          </div>
        </div>

        <div>
          <p className="jk-label mb-2" style={{ color: 'var(--team2-color)' }}>Team 2</p>
          <div className={isSingles ? 'grid grid-cols-1 gap-3' : 'grid grid-cols-2 gap-3'}>
            <PlayerPicker label={isSingles ? 'Player' : 'Player 1'} profiles={profiles} value={slots.t2p1} onChange={setSlot('t2p1')} excludeIds={chosenIds} />
            {!isSingles && (
              <PlayerPicker label="Player 2" profiles={profiles} value={slots.t2p2} onChange={setSlot('t2p2')} excludeIds={chosenIds} />
            )}
          </div>
        </div>

        <div className="flex items-center gap-4">
          <div>
            <p className="jk-label mb-1">Team 1 Score</p>
            <Input type="number" min={0} value={team1Score} onChange={(e) => setTeam1Score(e.target.value)} required />
          </div>
          <div>
            <p className="jk-label mb-1">Team 2 Score</p>
            <Input type="number" min={0} value={team2Score} onChange={(e) => setTeam2Score(e.target.value)} required />
          </div>
        </div>

        <label className="flex items-center gap-2" style={{ fontFamily: 'var(--font-body)', fontSize: 14 }}>
          <input type="checkbox" checked={ranked} onChange={(e) => setRanked(e.target.checked)} />
          Ranked (affects ELO)
        </label>

        {tournamentId && isAdmin && allSlotsFilled && (
          <div className="flex flex-col gap-2" style={{ color: 'var(--text-secondary)' }}>
            <p className="jk-label">Tournament participation</p>
            <p className="text-sm">Mark only substitute players to exclude them from group-stage standings and seeding. Ranked games still affect their ELO.</p>
            {chosenIds.map((uid) => {
              const profile = Object.values(slots).find((p) => p?.user_id === uid);
              return (
                <label key={uid} className="flex items-center gap-2 text-sm">
                  <input
                    type="checkbox"
                    checked={Boolean(substituteIds[uid])}
                    onChange={(e) => setSubstituteIds((current) => ({ ...current, [uid]: e.target.checked }))}
                  />
                  {profile.display_name} is a substitute
                </label>
              );
            })}
          </div>
        )}

        {allSlotsFilled && (
          <div className="flex flex-col gap-1.5">
            <p className="jk-label">Sinks (optional)</p>
            {chosenIds.map((uid) => {
              const profile = Object.values(slots).find((p) => p?.user_id === uid);
              return (
                <SinkCountInput
                  key={uid}
                  name={profile.display_name}
                  statLabel="sinks"
                  value={sinks[uid] || 0}
                  onChange={(v) => setSinks((s) => ({ ...s, [uid]: v }))}
                />
              );
            })}
          </div>
        )}

        {allSlotsFilled && (
          <div className="flex flex-col gap-1.5">
            <p className="jk-label">Self sinks (optional)</p>
            {chosenIds.map((uid) => {
              const profile = Object.values(slots).find((p) => p?.user_id === uid);
              return (
                <SinkCountInput
                  key={uid}
                  name={profile.display_name}
                  statLabel="self sinks"
                  value={selfSinks[uid] || 0}
                  onChange={(v) => setSelfSinks((s) => ({ ...s, [uid]: v }))}
                />
              );
            })}
          </div>
        )}

        {error && <p style={{ color: 'var(--state-danger)', fontSize: 13 }}>{error}</p>}
        {!scoresValid && team1Score !== '' && team2Score !== '' && (
          <p style={{ color: 'var(--state-danger)', fontSize: 13 }}>Scores can't tie — there must be a winner.</p>
        )}

        <Button type="submit" disabled={!canSubmit} style={{ background: 'var(--accent-primary)', color: '#fff' }}>
          {submitting ? 'Saving…' : editMode ? 'Save Changes' : 'Log Match'}
        </Button>
      </form>
    </div>
  );
}
