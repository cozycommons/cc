import React from 'react';
import { Link } from 'react-router-dom';
import PlayerAvatar from './PlayerAvatar.jsx';
import { teamPlayers, formatDate } from '../utils.js';

function TeamNames({ players, align = 'left' }) {
  return (
    <div className="min-w-0" style={{ textAlign: align }}>
      {players.map((p) => (
        <span
          key={p.user_id}
          className="truncate block"
          style={{ fontFamily: 'var(--font-body)', fontSize: 12, lineHeight: 1.35, color: 'var(--text-secondary)' }}
        >
          {p.display_name}
        </span>
      ))}
    </div>
  );
}

export default function GameRow({ game, perspectiveUserId, ratingDelta: authoritativeRatingDelta, story }) {
  const team1 = teamPlayers(game, 1);
  const team2 = teamPlayers(game, 2);

  const perspectivePlayer = perspectiveUserId
    ? (game.players || []).find((p) => p.user_id === perspectiveUserId)
    : null;
  const result = perspectivePlayer && game.winner_team != null
    ? (perspectivePlayer.team === game.winner_team ? 'win' : 'loss')
    : null;
  const snapshotRatingDelta = perspectivePlayer?.elo_before != null && perspectivePlayer?.elo_after != null
    ? perspectivePlayer.elo_after - perspectivePlayer.elo_before
    : null;
  const ratingDelta = authoritativeRatingDelta === undefined
    ? snapshotRatingDelta
    : authoritativeRatingDelta;
  const ratingMovement = ratingDelta > 0 ? 'gained' : ratingDelta < 0 ? 'lost' : 'unchanged by';

  return (
    <Link
      to={`/dice/game/${game.id}`}
      className={`jk-row flex items-center justify-between gap-1.5 sm:gap-3 px-2.5 sm:px-4 py-2.5 sm:py-3${result ? ` jk-row-${result}` : ''}`}
      style={{ borderBottom: '1px solid var(--border-subtle)' }}
    >
      <div className="flex items-center gap-1.5 sm:gap-2 min-w-0 flex-1 basis-0">
        <div className="flex -space-x-2 flex-shrink-0">
          {team1.map((p) => (
            <PlayerAvatar key={p.user_id} profile={p} size={28} linkToProfile={false} />
          ))}
        </div>
        <TeamNames players={team1} />
      </div>

      <div className="flex flex-col items-center flex-shrink-0 px-1 sm:px-2">
        <span className="jk-display" style={{ fontSize: 18 }}>
          {game.team1_score} – {game.team2_score}
        </span>
        <span className="jk-label whitespace-nowrap" style={{ fontSize: 9 }}>
          {game.ranked ? 'Ranked' : 'Normal'} · {formatDate(game.played_at)}
        </span>
        {story && (
          <span className="mt-1 whitespace-nowrap" style={{ fontFamily: 'var(--font-body)', fontSize: 10, color: 'var(--accent-primary)', fontWeight: 600 }}>
            {story}
          </span>
        )}
        {ratingDelta != null && (
          <span
            aria-label={`Rating ${ratingMovement} ${Math.abs(ratingDelta)} points`}
            style={{ fontFamily: 'var(--font-mono)', fontSize: 10, fontWeight: 700,
              color: ratingDelta >= 0 ? 'var(--state-success)' : 'var(--text-tertiary)' }}
          >
            {ratingDelta > 0 ? '+' : ''}{ratingDelta} ELO
          </span>
        )}
      </div>

      <div className="flex items-center gap-1.5 sm:gap-2 min-w-0 flex-1 basis-0 justify-end">
        <TeamNames players={team2} align="right" />
        <div className="flex -space-x-2 flex-shrink-0">
          {team2.map((p) => (
            <PlayerAvatar key={p.user_id} profile={p} size={28} linkToProfile={false} />
          ))}
        </div>
      </div>
    </Link>
  );
}
