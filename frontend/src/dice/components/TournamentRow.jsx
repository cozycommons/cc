import React from 'react';
import { Link } from 'react-router-dom';
import PlayerAvatar from './PlayerAvatar.jsx';
import { formatTournamentDateTime } from '../timezone.js';

export default function TournamentRow({ tournament }) {
  const players = tournament.enrolled_players || [];
  return (
    <Link
      to={`/dice/tournament/${tournament.id}`}
      className="jk-row flex items-center justify-between gap-3 px-2.5 sm:px-4 py-2.5 sm:py-3"
      style={{ borderBottom: '1px solid var(--border-subtle)' }}
    >
      <div className="min-w-0 flex-1">
        <p
          className="truncate"
          style={{ fontFamily: 'var(--font-body)', fontWeight: 600, fontSize: 14, color: 'var(--text-primary)' }}
        >
          {tournament.name}
        </p>
        <p className="jk-label" style={{ fontSize: 10 }}>
          {formatTournamentDateTime(tournament.starts_at)} · {players.length} enrolled
        </p>
      </div>
      <div className="flex -space-x-2 flex-shrink-0">
        {players.slice(0, 5).map((p) => (
          <PlayerAvatar key={p.user_id} profile={p} size={26} linkToProfile={false} />
        ))}
        {players.length > 5 && (
          <div
            className="flex items-center justify-center"
            style={{
              width: 26,
              height: 26,
              borderRadius: '50%',
              background: 'var(--surface-sunken)',
              border: '1px solid var(--border-subtle)',
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
              color: 'var(--text-tertiary)',
            }}
          >
            +{players.length - 5}
          </div>
        )}
      </div>
    </Link>
  );
}
