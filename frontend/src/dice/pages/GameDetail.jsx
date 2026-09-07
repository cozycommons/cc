import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { diceApi } from '../api.js';
import PlayerAvatar from '../components/PlayerAvatar.jsx';
import CommentsSection from '../components/CommentsSection.jsx';
import { teamAverageElo, teamPlayers, formatDate, canEditGame } from '../utils.js';

function PlayerColumn({ player }) {
  const delta = player.elo_after != null && player.elo_before != null
    ? player.elo_after - player.elo_before
    : null;
  return (
    <div className="flex flex-col items-center gap-1.5 w-24">
      <PlayerAvatar profile={player} size={56} />
      <span
        className="truncate w-full text-center"
        style={{ fontFamily: 'var(--font-body)', fontWeight: 500, fontSize: 13, color: 'var(--text-primary)' }}
      >
        {player.display_name}
      </span>
      {player.elo_before != null && (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-tertiary)' }}>
          {player.elo_before} ELO
          {delta != null && (
            <span style={{ color: delta >= 0 ? 'var(--state-success)' : 'var(--state-danger)' }}>
              {' '}{delta >= 0 ? `+${delta}` : delta}
            </span>
          )}
        </span>
      )}
      {player.sinks > 0 && (
        <span
          className="jk-label"
          style={{ fontSize: 10, color: 'var(--text-tertiary)' }}
          title="Sinks"
        >
          🎯 {player.sinks} sink{player.sinks === 1 ? '' : 's'}
        </span>
      )}
      {player.self_sinks > 0 && (
        <span
          className="jk-label"
          style={{ fontSize: 10, color: 'var(--state-warning)' }}
          title="Self sinks"
        >
          🎱 {player.self_sinks} self sink{player.self_sinks === 1 ? '' : 's'}
        </span>
      )}
    </div>
  );
}

function Team({ game, team, side }) {
  const players = teamPlayers(game, team);
  const avg = teamAverageElo(game, team);
  const won = game.winner_team === team;
  return (
    <div className="w-full sm:flex-1 flex flex-col items-center gap-3 sm:gap-4">
      <div className="flex items-center gap-2">
        <span
          className="jk-label"
          style={{ color: side === 'left' ? 'var(--team1-color)' : 'var(--team2-color)' }}
        >
          Team {team}
        </span>
        {won && (
          <span
            className="jk-label"
            style={{ background: 'var(--state-success)', color: '#fff', padding: '2px 8px', borderRadius: 'var(--radius-pill)' }}
          >
            WIN
          </span>
        )}
      </div>
      <div className="flex gap-3 sm:gap-4">
        {players.map((p) => (
          <PlayerColumn key={p.user_id} player={p} />
        ))}
      </div>
      {avg != null && (
        <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-tertiary)' }}>
          Team avg: {avg} ELO
        </span>
      )}
    </div>
  );
}

export default function GameDetail({ auth }) {
  const { gameId } = useParams();
  const navigate = useNavigate();
  const { user, token, isAdmin } = auth;
  const [game, setGame] = useState(null);
  const [error, setError] = useState(null);
  const [deleting, setDeleting] = useState(false);

  useEffect(() => {
    diceApi.getGame(gameId).then(setGame).catch(() => setGame(null));
  }, [gameId]);

  if (game === null) {
    return <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8">Loading…</div>;
  }

  const editable = canEditGame(game, user, isAdmin);

  const handleDelete = async () => {
    if (!window.confirm('Delete this match? This cannot be undone.')) return;
    setDeleting(true);
    setError(null);
    try {
      await diceApi.deleteGame(token, gameId);
      navigate('/dice');
    } catch (err) {
      setError('Failed to delete match.');
      setDeleting(false);
    }
  };

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8">
      <div className="jk-card p-5 sm:p-10 overflow-hidden">
        <div className="flex flex-col sm:flex-row items-center sm:items-stretch justify-between gap-5 sm:gap-4 mb-2 sm:mb-6">
          <Team game={game} team={1} side="left" />
          <div className="flex flex-col items-center justify-center sm:px-2 flex-shrink-0">
            <span className="jk-display" style={{ fontSize: 36, lineHeight: 1 }}>
              {game.team1_score} – {game.team2_score}
            </span>
            <span className="jk-label mt-2">{game.ranked ? 'Ranked' : 'Normal'}</span>
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-tertiary)' }} className="mt-1">
              {formatDate(game.played_at)}
            </span>
          </div>
          <Team game={game} team={2} side="right" />
        </div>
      </div>

      {editable && (
        <div className="flex gap-2 mt-4 justify-end">
          <Button size="sm" variant="outline" onClick={() => navigate(`/dice/game/${gameId}/edit`)}>
            Edit
          </Button>
          <Button size="sm" variant="destructive" onClick={handleDelete} disabled={deleting}>
            {deleting ? 'Deleting…' : 'Delete'}
          </Button>
        </div>
      )}
      {error && <p style={{ color: 'var(--state-danger)', fontSize: 13 }} className="mt-2 text-right">{error}</p>}

      <CommentsSection gameId={gameId} auth={auth} />
    </div>
  );
}
