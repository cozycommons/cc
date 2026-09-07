import React from 'react';
import { Link } from 'react-router-dom';
import PlayerAvatar from './PlayerAvatar.jsx';

export default function LeaderboardRow({
  rank,
  profile,
  value,
  valueLabel,
  unranked = false,
  tied = false,
  barMode,
  maxValue = 0,
  isCurrentUser = false,
  barTone = 'sky',
}) {
  const rankLabel = unranked || rank == null ? '—' : `${rank}`;
  const countWidth = maxValue > 0 ? Math.max(0, Math.min(100, (value / maxValue) * 100)) : 0;
  const eloRange = maxValue > 0 ? maxValue : 400;
  const eloOffset = Math.max(-eloRange, Math.min(eloRange, value - 1500));
  const eloWidth = (Math.abs(eloOffset) / eloRange) * 50;

  return (
    <Link
      to={`/dice/profile/${profile.user_id}`}
      className={`jk-row jk-leaderboard-row block px-4 py-2.5${isCurrentUser ? ' jk-leaderboard-row-me' : ''}`}
      style={{ borderBottom: '1px solid var(--border-subtle)' }}
      aria-label={`${rank ? `Rank ${rank}, ` : ''}${profile.display_name}, ${unranked ? 'unranked' : `${value} ${valueLabel || ''}`}${isCurrentUser ? ', you' : ''}`}
    >
      <div className="flex items-center gap-3">
        <span
          aria-label={unranked ? 'Unranked' : tied ? `Tied rank ${rank}` : `Rank ${rank}`}
          className="jk-label flex-shrink-0"
          style={{ width: 22, textAlign: 'center', fontSize: 14, color: 'var(--text-tertiary)' }}
        >
          {rankLabel}
        </span>
        <PlayerAvatar profile={profile} size={32} linkToProfile={false} />
        <span className="flex-1 min-w-0 truncate" style={{ fontFamily: 'var(--font-body)', fontWeight: 500, fontSize: 14, color: 'var(--text-primary)' }}>
          {profile.display_name}
          {isCurrentUser && <span className="jk-label ml-2" style={{ fontSize: 8, color: 'var(--accent-clay)' }}>You</span>}
        </span>
        {unranked ? (
          <span className="flex-shrink-0" style={{ fontFamily: 'var(--font-mono)', fontSize: 9, fontWeight: 600, color: 'var(--text-on-strong)', background: 'var(--surface-strong)', borderRadius: 3, padding: '2px 6px', letterSpacing: '0.03em', whiteSpace: 'nowrap' }}>
            UNRANKED
          </span>
        ) : (
          <span className="flex-shrink-0" style={{ fontFamily: 'var(--font-mono)', fontSize: 14, color: 'var(--text-primary)' }}>
            {value}
            {valueLabel && <span style={{ color: 'var(--text-tertiary)', marginLeft: 4, fontSize: 11 }}>{valueLabel}</span>}
          </span>
        )}
      </div>
      {barMode && !unranked && (
        <div
          className={`jk-leaderboard-track mt-2 ${barMode === 'elo' ? 'jk-leaderboard-track-elo' : ''}`}
          role="img"
          aria-label={barMode === 'elo' ? `${Math.abs(value - 1500)} points ${value >= 1500 ? 'above' : 'below'} 1500` : `${value} out of ${maxValue}`}
        >
          {barMode === 'elo' ? (
            <span className={`jk-leaderboard-bar jk-leaderboard-bar-elo ${eloOffset >= 0 ? 'is-positive' : 'is-negative'}`} style={{ width: `${eloWidth}%` }} />
          ) : (
            <span className={`jk-leaderboard-bar is-${barTone}`} style={{ width: `${countWidth}%` }} />
          )}
        </div>
      )}
    </Link>
  );
}
