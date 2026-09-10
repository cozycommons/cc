import React, { useEffect, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { diceApi } from '../api.js';
import PlayerAvatar from '../components/PlayerAvatar.jsx';
import Linkify from '../components/Linkify.jsx';
import RosterPicker from '../components/RosterPicker.jsx';
import GameRow from '../components/GameRow.jsx';
import BracketView from '../components/BracketView.jsx';
import { canEditTournament, isEnrolled, computeTournamentStandings, hasDuplicatePlayerIds } from '../utils.js';
import { formatTournamentDateTime } from '../timezone.js';

function PlayerChip({ profile }) {
  return (
    <div className="flex items-center gap-2 px-2.5 py-1.5" style={{ background: 'var(--surface-sunken)', borderRadius: 'var(--radius-pill)' }}>
      <PlayerAvatar profile={profile} size={22} linkToProfile={false} />
      <span style={{ fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--text-primary)' }}>
        {profile.display_name}
      </span>
    </div>
  );
}

function MatchSlot({ player }) {
  return (
    <div className="flex flex-col items-center gap-1 shrink-0" style={{ width: 68 }}>
      {player.user_id ? (
        <PlayerAvatar profile={player} size={32} linkToProfile={false} />
      ) : (
        <div
          style={{
            width: 32,
            height: 32,
            borderRadius: '50%',
            background: 'var(--surface-sunken)',
            border: '1px dashed var(--border-default)',
          }}
        />
      )}
      <span
        className="truncate w-full text-center"
        style={{
          fontFamily: 'var(--font-body)',
          fontSize: 11,
          color: player.user_id ? 'var(--text-primary)' : 'var(--text-tertiary)',
        }}
      >
        {player.display_name}
      </span>
    </div>
  );
}

function ScheduledMatchRow({ match, editable, canEnterResult, onEdit, onDelete, onEnterResult }) {
  return (
    <div className="jk-card p-3 flex flex-col gap-3">
      <div className="flex items-center justify-center gap-2 flex-wrap">
        <div className="flex gap-2 flex-wrap justify-center">{match.team1.map((p, i) => <MatchSlot key={i} player={p} />)}</div>
        <span className="jk-label shrink-0">vs</span>
        <div className="flex gap-2 flex-wrap justify-center">{match.team2.map((p, i) => <MatchSlot key={i} player={p} />)}</div>
      </div>
      <div className="flex items-center justify-between gap-3 flex-wrap">
        {match.label && <span className="jk-label">{match.label}</span>}
        <div className="flex items-center gap-3 flex-wrap">
          {canEnterResult && (
            <Button size="sm" variant="outline" onClick={onEnterResult}>
              Enter Result
            </Button>
          )}
          {editable && (
            <div className="flex gap-2">
              <button
                type="button"
                onClick={onEdit}
                style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-tertiary)' }}
              >
                Edit
              </button>
              <button
                type="button"
                onClick={onDelete}
                style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--state-danger)' }}
              >
                Delete
              </button>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}

function PlayerSelect({ players, value, onChange }) {
  return (
    <select
      value={value || ''}
      onChange={(e) => onChange(e.target.value || null)}
      className="w-full"
      style={{
        fontFamily: 'var(--font-body)',
        fontSize: 13,
        padding: '6px 8px',
        border: '1px solid var(--border-default)',
        borderRadius: 'var(--radius-md)',
        background: 'var(--surface-card)',
        color: 'var(--text-primary)',
      }}
    >
      <option value="">TBD</option>
      {players.map((p) => (
        <option key={p.user_id} value={p.user_id}>
          {p.display_name}
        </option>
      ))}
    </select>
  );
}

export function selectBracketTeamPlayer(team, index, userId, isSingles) {
  if (isSingles) return [userId];
  return team.map((current, slot) => (slot === index ? userId : current));
}

function FormatToggle({ value, onChange }) {
  return (
    <div className="inline-flex shrink-0" style={{ border: '1px solid var(--border-default)', borderRadius: 'var(--radius-pill)', overflow: 'hidden' }}>
      {['2v2', '1v1'].map((type) => (
        <button
          key={type}
          type="button"
          onClick={() => onChange(type)}
          style={{
            fontFamily: 'var(--font-body)',
            fontSize: 12,
            fontWeight: 500,
            padding: '4px 12px',
            background: value === type ? 'var(--accent-primary)' : 'transparent',
            color: value === type ? '#fff' : 'var(--text-secondary)',
          }}
        >
          {type}
        </button>
      ))}
    </div>
  );
}

function ScheduledMatchForm({ tournamentId, enrolledPlayers, token, editingMatch, onSaved, onCancel }) {
  const [label, setLabel] = useState(editingMatch?.label || '');
  const [format, setFormat] = useState(editingMatch && editingMatch.team1.length === 1 ? '1v1' : '2v2');
  const [team1, setTeam1] = useState(editingMatch ? editingMatch.team1.map((p) => p.user_id) : [null, null]);
  const [team2, setTeam2] = useState(editingMatch ? editingMatch.team2.map((p) => p.user_id) : [null, null]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const isSingles = format === '1v1';

  const hasDuplicate = hasDuplicatePlayerIds(team1, team2);

  const changeFormat = (next) => {
    setFormat(next);
    const trim = (t) => (next === '1v1' ? [t[0]] : [t[0], t[1] ?? null]);
    setTeam1(trim);
    setTeam2(trim);
  };

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (hasDuplicate) {
      setError('Each player can only appear once in a match.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const payload = { label: label.trim() || null, team1_player_ids: team1, team2_player_ids: team2 };
      const updated = editingMatch
        ? await diceApi.updateScheduledMatch(token, tournamentId, editingMatch.id, payload)
        : await diceApi.addScheduledMatch(token, tournamentId, payload);
      onSaved(updated);
    } catch (err) {
      setError('Failed to save match.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="jk-card p-4 flex flex-col gap-3">
      <div className="flex items-center gap-3">
        <Input placeholder="Label (optional), e.g. Round 1" value={label} onChange={(e) => setLabel(e.target.value)} className="flex-1" />
        <FormatToggle value={format} onChange={changeFormat} />
      </div>
      <div className="flex items-start gap-3">
        <div className="flex-1 flex flex-col gap-1.5">
          <span className="jk-label" style={{ color: 'var(--team1-color)' }}>Team 1</span>
          <PlayerSelect players={enrolledPlayers} value={team1[0]} onChange={(v) => setTeam1((t) => [v, t[1]])} />
          {!isSingles && (
            <PlayerSelect players={enrolledPlayers} value={team1[1]} onChange={(v) => setTeam1((t) => [t[0], v])} />
          )}
        </div>
        <span className="jk-display mt-6" style={{ fontSize: 16 }}>vs</span>
        <div className="flex-1 flex flex-col gap-1.5">
          <span className="jk-label" style={{ color: 'var(--team2-color)' }}>Team 2</span>
          <PlayerSelect players={enrolledPlayers} value={team2[0]} onChange={(v) => setTeam2((t) => [v, t[1]])} />
          {!isSingles && (
            <PlayerSelect players={enrolledPlayers} value={team2[1]} onChange={(v) => setTeam2((t) => [t[0], v])} />
          )}
        </div>
      </div>
      {hasDuplicate && (
        <p style={{ color: 'var(--state-danger)', fontSize: 13 }}>
          Each player can only appear once in a match.
        </p>
      )}
      {error && <p style={{ color: 'var(--state-danger)', fontSize: 13 }}>{error}</p>}
      <div className="flex gap-2 justify-end">
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" size="sm" disabled={submitting || hasDuplicate} style={{ background: 'var(--accent-primary)', color: '#fff' }}>
          {submitting ? 'Saving…' : editingMatch ? 'Save' : 'Add Match'}
        </Button>
      </div>
    </form>
  );
}

// Lets a host explicitly assemble the 4 bracket teams from the finalist
// pool, independent of the order finalists were added in. Team 1 plays
// Team 2 in one semifinal, Team 3 plays Team 4 in the other.
// Team numbering follows the bracket's visual layout: Team 1 & Team 3 are
// the left side (semi1), Team 2 & Team 4 are the right side (semi2) — see
// BracketView, where semi1 renders on the left and semi2 on the right.
function BracketTeamsForm({ tournamentId, finalists, bracket, token, onSaved, onCancel }) {
  const [format, setFormat] = useState(bracket.semi1.team1.length === 1 ? '1v1' : '2v2');
  const [team1, setTeam1] = useState(bracket.semi1.team1.map((p) => p.user_id));
  const [team3, setTeam3] = useState(bracket.semi1.team2.map((p) => p.user_id));
  const [team2, setTeam2] = useState(bracket.semi2.team1.map((p) => p.user_id));
  const [team4, setTeam4] = useState(bracket.semi2.team2.map((p) => p.user_id));
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const isSingles = format === '1v1';

  const selectPlayer = (team, setTeam, index, userId) => {
    setTeam(selectBracketTeamPlayer(team, index, userId, isSingles));
  };

  const changeFormat = (next) => {
    setFormat(next);
    const trim = (t) => (next === '1v1' ? [t[0]] : [t[0], t[1] ?? null]);
    setTeam1(trim);
    setTeam2(trim);
    setTeam3(trim);
    setTeam4(trim);
  };

  const hasDuplicate = hasDuplicatePlayerIds(team1, team2, team3, team4);

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (hasDuplicate) {
      setError('Each finalist can only be assigned to one team.');
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      const payload = {
        team1_player_ids: team1,
        team2_player_ids: team2,
        team3_player_ids: team3,
        team4_player_ids: team4,
      };
      const updated = await diceApi.setBracketTeams(token, tournamentId, payload);
      onSaved(updated);
    } catch (err) {
      setError('Failed to save teams.');
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <form onSubmit={handleSubmit} className="jk-card p-4 flex flex-col gap-3">
      <div className="flex items-center justify-between gap-3 flex-wrap">
        <p style={{ fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--text-secondary)' }}>
          Team 1 plays Team 3 on the bracket's left side; Team 2 plays Team 4 on the right.
        </p>
        <FormatToggle value={format} onChange={changeFormat} />
      </div>
      <div className="flex items-start gap-4">
        <div className="flex-1 flex flex-col gap-2">
          <span className="jk-label" style={{ color: 'var(--text-secondary)' }}>Left Semifinal</span>
          <div className="flex flex-col gap-1.5">
            <span className="jk-label">Team 1</span>
            <PlayerSelect players={finalists} value={team1[0]} onChange={(v) => selectPlayer(team1, setTeam1, 0, v)} />
            {!isSingles && (
              <PlayerSelect players={finalists} value={team1[1]} onChange={(v) => selectPlayer(team1, setTeam1, 1, v)} />
            )}
          </div>
          <span className="jk-display text-center" style={{ fontSize: 14 }}>vs</span>
          <div className="flex flex-col gap-1.5">
            <span className="jk-label">Team 3</span>
            <PlayerSelect players={finalists} value={team3[0]} onChange={(v) => selectPlayer(team3, setTeam3, 0, v)} />
            {!isSingles && (
              <PlayerSelect players={finalists} value={team3[1]} onChange={(v) => selectPlayer(team3, setTeam3, 1, v)} />
            )}
          </div>
        </div>
        <div className="flex-1 flex flex-col gap-2">
          <span className="jk-label" style={{ color: 'var(--text-secondary)' }}>Right Semifinal</span>
          <div className="flex flex-col gap-1.5">
            <span className="jk-label">Team 2</span>
            <PlayerSelect players={finalists} value={team2[0]} onChange={(v) => selectPlayer(team2, setTeam2, 0, v)} />
            {!isSingles && (
              <PlayerSelect players={finalists} value={team2[1]} onChange={(v) => selectPlayer(team2, setTeam2, 1, v)} />
            )}
          </div>
          <span className="jk-display text-center" style={{ fontSize: 14 }}>vs</span>
          <div className="flex flex-col gap-1.5">
            <span className="jk-label">Team 4</span>
            <PlayerSelect players={finalists} value={team4[0]} onChange={(v) => selectPlayer(team4, setTeam4, 0, v)} />
            {!isSingles && (
              <PlayerSelect players={finalists} value={team4[1]} onChange={(v) => selectPlayer(team4, setTeam4, 1, v)} />
            )}
          </div>
        </div>
      </div>
      {error && <p style={{ color: 'var(--state-danger)', fontSize: 13 }}>{error}</p>}
      <div className="flex gap-2 justify-end">
        <Button type="button" size="sm" variant="ghost" onClick={onCancel}>
          Cancel
        </Button>
        <Button type="submit" size="sm" disabled={submitting} style={{ background: 'var(--accent-primary)', color: '#fff' }}>
          {submitting ? 'Saving…' : 'Save Teams'}
        </Button>
      </div>
    </form>
  );
}

export default function TournamentDetail({ auth }) {
  const { tournamentId } = useParams();
  const navigate = useNavigate();
  const { user, token, isAdmin } = auth;
  const [tournament, setTournament] = useState(null);
  const [profiles, setProfiles] = useState(null);
  const [error, setError] = useState(null);
  const [busy, setBusy] = useState(false);
  const [addingPlayer, setAddingPlayer] = useState(false);
  const [matchForm, setMatchForm] = useState(null); // null | 'new' | a match object being edited
  const [addingFinalist, setAddingFinalist] = useState(false);
  const [finalistBusy, setFinalistBusy] = useState(false);
  const [formingTeams, setFormingTeams] = useState(false);

  const load = () => diceApi.getTournament(tournamentId).then(setTournament).catch(() => setTournament(false));

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tournamentId]);

  useEffect(() => {
    diceApi.searchProfiles('', 100).then(setProfiles).catch((err) => {
      console.error('Failed to load players for the add-player picker:', err);
      setProfiles([]);
    });
  }, []);

  if (tournament === null) {
    return <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8">Loading…</div>;
  }
  if (tournament === false) {
    return <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8">Tournament not found.</div>;
  }

  const editable = canEditTournament(tournament, user, isAdmin);
  const enrolled = isEnrolled(tournament, user);

  const handleEnrollToggle = async () => {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      const updated = enrolled
        ? await diceApi.unenrollFromTournament(token, tournamentId)
        : await diceApi.enrollInTournament(token, tournamentId);
      setTournament(updated);
    } catch (err) {
      setError('Failed to update enrollment.');
    } finally {
      setBusy(false);
    }
  };

  const handleAddPlayer = async (profile) => {
    if (!token) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await diceApi.enrollInTournament(token, tournamentId, profile.user_id);
      setTournament(updated);
      setAddingPlayer(false);
    } catch (err) {
      setError('Failed to add player.');
    } finally {
      setBusy(false);
    }
  };

  const handleDeleteMatch = async (matchId) => {
    if (!window.confirm('Delete this scheduled match?')) return;
    setBusy(true);
    setError(null);
    try {
      const updated = await diceApi.deleteScheduledMatch(token, tournamentId, matchId);
      setTournament(updated);
    } catch (err) {
      setError('Failed to delete match.');
    } finally {
      setBusy(false);
    }
  };

  const handleDelete = async () => {
    if (!window.confirm('Delete this tournament? This cannot be undone.')) return;
    setBusy(true);
    setError(null);
    try {
      await diceApi.deleteTournament(token, tournamentId);
      navigate('/dice/tournaments');
    } catch (err) {
      setError('Failed to delete tournament.');
      setBusy(false);
    }
  };

  // Shared by both "Enter Result" flows below — a match's team size (1 or
  // 2 players) determines whether LogMatch logs it as 1v1 or 2v2.
  const buildMatchNavState = (match) => ({
    matchType: match.team1.length === 1 ? '1v1' : '2v2',
    prefill: {
      t1p1: match.team1[0].user_id,
      t1p2: match.team1[1]?.user_id ?? null,
      t2p1: match.team2[0].user_id,
      t2p2: match.team2[1]?.user_id ?? null,
    },
  });

  const handleEnterResult = (match) => {
    navigate('/dice/log', {
      state: {
        tournamentId,
        scheduledMatchId: match.id,
        ...buildMatchNavState(match),
      },
    });
  };

  const handleLogManualGame = () => {
    navigate('/dice/log', { state: { tournamentId } });
  };

  const handleAddFinalist = async (profile) => {
    if (!token) return;
    setFinalistBusy(true);
    setError(null);
    try {
      const updated = await diceApi.addFinalist(token, tournamentId, profile.user_id);
      setTournament(updated);
      setAddingFinalist(false);
    } catch (err) {
      setError('Failed to add finalist.');
    } finally {
      setFinalistBusy(false);
    }
  };

  const handleRemoveFinalist = async (userId) => {
    setFinalistBusy(true);
    setError(null);
    try {
      const updated = await diceApi.removeFinalist(token, tournamentId, userId);
      setTournament(updated);
    } catch (err) {
      setError('Failed to remove finalist.');
    } finally {
      setFinalistBusy(false);
    }
  };

  const handleBracketEnterResult = (slotId) => {
    const match = tournament.bracket[slotId];
    navigate('/dice/log', {
      state: {
        tournamentId,
        bracketSlot: slotId,
        ...buildMatchNavState(match),
      },
    });
  };

  const standings = computeTournamentStandings(tournament);

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8">
      <div className="jk-card p-6 sm:p-8">
        <p className="jk-display" style={{ fontSize: 30 }}>{tournament.name}</p>
        <p className="jk-label mt-1">{formatTournamentDateTime(tournament.starts_at)}</p>

        {tournament.description && (
          <p
            className="mt-4"
            style={{ fontFamily: 'var(--font-body)', fontSize: 14, color: 'var(--text-secondary)', whiteSpace: 'pre-wrap' }}
          >
            <Linkify text={tournament.description} />
          </p>
        )}

        {enrolled && (
          <Link
            to={`/dice/tournament/${tournamentId}/virtual`}
            className="mt-5 flex items-center justify-between gap-3 p-4 rounded-md"
            style={{ background: 'var(--surface-strong)', color: 'var(--text-on-strong)' }}
          >
            <span>
              <span className="jk-label block" style={{ color: 'inherit' }}>VIRTUAL DICE</span>
              <span className="text-sm">Make pregame picks with tournament Dice</span>
            </span>
            <span aria-hidden="true">→</span>
          </Link>
        )}

        <div className="mt-6">
          <p className="jk-label mb-2">// Hosts</p>
          <div className="flex flex-wrap gap-2">
            {tournament.hosts.length === 0 && (
              <p style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>No hosts assigned.</p>
            )}
            {tournament.hosts.map((h) => <PlayerChip key={h.user_id} profile={h} />)}
          </div>
        </div>

        <div className="mt-6">
          <div className="flex items-center justify-between mb-2">
            <p className="jk-label">// Enrolled Players ({tournament.enrolled_players.length})</p>
            <div className="flex gap-2">
              {editable && (
                <Button size="sm" variant="outline" onClick={() => setAddingPlayer((v) => !v)}>
                  {addingPlayer ? 'Cancel' : '+ Add Player'}
                </Button>
              )}
              {user && (
                <Button size="sm" variant={enrolled ? 'outline' : 'default'} onClick={handleEnrollToggle} disabled={busy}
                  style={enrolled ? {} : { background: 'var(--accent-primary)', color: '#fff' }}>
                  {busy ? '…' : enrolled ? 'Unenroll' : 'Enroll'}
                </Button>
              )}
            </div>
          </div>
          {addingPlayer && (
            <div className="mb-3">
              <RosterPicker
                profiles={profiles}
                excludeIds={tournament.enrolled_players.map((p) => p.user_id)}
                onPick={handleAddPlayer}
                placeholder="Add a player to this tournament…"
                allTakenMessage="Everyone in the roster is already enrolled."
              />
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {tournament.enrolled_players.length === 0 && (
              <p style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>No one has enrolled yet.</p>
            )}
            {tournament.enrolled_players.map((p) => <PlayerChip key={p.user_id} profile={p} />)}
          </div>
          {!user && (
            <p className="mt-2" style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>Sign in to enroll.</p>
          )}
        </div>

        {standings.length > 0 && (
          <div className="mt-6">
            <p className="jk-label mb-2">// Standings</p>
            <div className="jk-card overflow-hidden">
              {standings.map((s, i) => (
                <Link
                  key={s.user_id}
                  to={`/dice/profile/${s.user_id}`}
                  className="jk-row flex items-center gap-3 px-3 py-2"
                  style={{ borderBottom: '1px solid var(--border-subtle)' }}
                >
                  <span className="jk-label" style={{ width: 20 }}>{i + 1}</span>
                  <PlayerAvatar profile={s} size={26} linkToProfile={false} />
                  <span className="flex-1" style={{ fontFamily: 'var(--font-body)', fontSize: 14, color: 'var(--text-primary)' }}>
                    {s.display_name}
                  </span>
                  <span className="flex-shrink-0" style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-tertiary)' }}>
                    {s.self_sinks}
                    <span style={{ fontSize: 10, marginLeft: 3 }}>self sinks</span>
                  </span>
                  <span style={{ fontFamily: 'var(--font-mono)', fontSize: 13, color: 'var(--text-secondary)' }}>
                    {s.wins}-{s.losses}
                  </span>
                </Link>
              ))}
            </div>
          </div>
        )}

        <div className="mt-6">
          <div className="flex items-center justify-between mb-2">
            <p className="jk-label">// Group Stage · Schedule</p>
            <div className="flex items-center gap-2">
              {isAdmin && (
                <Button size="sm" variant="outline" onClick={handleLogManualGame}>
                  + Log Game
                </Button>
              )}
              {editable && matchForm === null && (
                <Button size="sm" variant="outline" onClick={() => setMatchForm('new')}>
                  + Add Match
                </Button>
              )}
            </div>
          </div>
          <div className="flex flex-col gap-2">
            {tournament.scheduled_matches.length === 0 && matchForm === null && (
              <p style={{ fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--text-tertiary)' }}>TBD</p>
            )}
            {tournament.scheduled_matches.map((match) =>
              matchForm && matchForm !== 'new' && matchForm.id === match.id ? (
                <ScheduledMatchForm
                  key={match.id}
                  tournamentId={tournamentId}
                  enrolledPlayers={tournament.enrolled_players}
                  token={token}
                  editingMatch={matchForm}
                  onSaved={(updated) => {
                    setTournament(updated);
                    setMatchForm(null);
                  }}
                  onCancel={() => setMatchForm(null)}
                />
              ) : (
                <ScheduledMatchRow
                  key={match.id}
                  match={match}
                  editable={editable}
                  canEnterResult={!!user && [...match.team1, ...match.team2].every((p) => p.user_id)}
                  onEdit={() => setMatchForm(match)}
                  onDelete={() => handleDeleteMatch(match.id)}
                  onEnterResult={() => handleEnterResult(match)}
                />
              )
            )}
            {matchForm === 'new' && (
              <ScheduledMatchForm
                tournamentId={tournamentId}
                enrolledPlayers={tournament.enrolled_players}
                token={token}
                editingMatch={null}
                onSaved={(updated) => {
                  setTournament(updated);
                  setMatchForm(null);
                }}
                onCancel={() => setMatchForm(null)}
              />
            )}
          </div>
        </div>

        {tournament.completed_games.length > 0 && (
          <div className="mt-6">
            <p className="jk-label mb-2">// Group Stage · Results</p>
            <div className="jk-card overflow-hidden">
              {tournament.completed_games.map((g) => <GameRow key={g.id} game={g} />)}
            </div>
          </div>
        )}

        <div className="mt-6">
          <div className="flex items-center justify-between mb-2">
            <p className="jk-label">// Finalists ({tournament.finalists.length}/8)</p>
            {editable && tournament.finalists.length < 8 && (
              <Button size="sm" variant="outline" onClick={() => setAddingFinalist((v) => !v)}>
                {addingFinalist ? 'Cancel' : '+ Add Finalist'}
              </Button>
            )}
          </div>
          {addingFinalist && (
            <div className="mb-3">
              <RosterPicker
                profiles={tournament.enrolled_players}
                excludeIds={tournament.finalists.map((p) => p.user_id)}
                onPick={handleAddFinalist}
                placeholder="Add a finalist from the enrolled players…"
                emptyRosterMessage="Enroll some players first."
                allTakenMessage="Every enrolled player is already a finalist."
              />
            </div>
          )}
          <div className="flex flex-wrap gap-2">
            {tournament.finalists.length === 0 && !addingFinalist && (
              <p style={{ fontSize: 13, color: 'var(--text-tertiary)' }}>No finalists yet.</p>
            )}
            {tournament.finalists.map((p) => (
              <div
                key={p.user_id}
                className="flex items-center gap-2 pl-1 pr-2.5 py-1.5"
                style={{ background: 'var(--surface-sunken)', borderRadius: 'var(--radius-pill)' }}
              >
                <PlayerAvatar profile={p} size={22} linkToProfile={false} />
                <span style={{ fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--text-primary)' }}>
                  {p.display_name}
                </span>
                {editable && (
                  <button
                    type="button"
                    onClick={() => handleRemoveFinalist(p.user_id)}
                    disabled={finalistBusy}
                    style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--state-danger)' }}
                  >
                    ×
                  </button>
                )}
              </div>
            ))}
          </div>
        </div>

        {tournament.finalists.length > 0 && (
          <div className="mt-6">
            <div className="flex items-center justify-between mb-3">
              <p className="jk-label">// Bracket</p>
              {editable && tournament.finalists.length >= 2 && (
                <Button size="sm" variant="outline" onClick={() => setFormingTeams((v) => !v)}>
                  {formingTeams ? 'Cancel' : 'Form Teams'}
                </Button>
              )}
            </div>
            {formingTeams ? (
              <BracketTeamsForm
                tournamentId={tournamentId}
                finalists={tournament.finalists}
                bracket={tournament.bracket}
                token={token}
                onSaved={(updated) => {
                  setTournament(updated);
                  setFormingTeams(false);
                }}
                onCancel={() => setFormingTeams(false)}
              />
            ) : (
              <BracketView
                bracket={tournament.bracket}
                canEnterUser={!!user}
                onEnterResult={handleBracketEnterResult}
              />
            )}
          </div>
        )}
      </div>

      {editable && (
        <div className="flex gap-2 mt-4 justify-end">
          <Button size="sm" variant="outline" onClick={() => navigate(`/dice/tournament/${tournamentId}/edit`)}>
            Edit
          </Button>
          <Button size="sm" variant="destructive" onClick={handleDelete} disabled={busy}>
            {busy ? 'Deleting…' : 'Delete'}
          </Button>
        </div>
      )}
      {error && <p style={{ color: 'var(--state-danger)', fontSize: 13 }} className="mt-2 text-right">{error}</p>}
    </div>
  );
}
