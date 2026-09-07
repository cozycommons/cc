import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { rankLeaderboard } from '../leaderboard.js';
import PlayerAvatar from './PlayerAvatar.jsx';

const MODES = {
  sinks: { label: 'Sinks', valueKey: 'sinks', to: '/dice/leaderboard/sinks', tone: 'sky' },
  selfSinks: { label: 'Self-sinks', valueKey: 'self_sinks', to: '/dice/leaderboard/self-sinks', tone: 'clay' },
};

export default function SinkLeadersChart({ sinks, selfSinks, currentUserId }) {
  const [mode, setMode] = useState('sinks');
  const config = MODES[mode];
  const entries = mode === 'sinks' ? sinks : selfSinks;
  const ranked = rankLeaderboard(entries, config.valueKey);
  const leaders = ranked.filter((profile) => profile[config.valueKey] > 0).slice(0, 5);
  const current = ranked.find((profile) => profile.user_id === currentUserId);
  const pinnedCurrent = current && !leaders.some((profile) => profile.user_id === current.user_id) ? current : null;
  const displayed = pinnedCurrent ? [...leaders, pinnedCurrent] : leaders;
  const maxValue = ranked[0]?.[config.valueKey] || 0;

  return (
    <div className="jk-card overflow-hidden">
      <div className="px-3 py-2 flex items-center justify-between gap-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
        <div className="jk-stat-toggle" role="group" aria-label="Sink statistic">
          {Object.entries(MODES).map(([key, candidate]) => (
            <button key={key} type="button" className={mode === key ? 'is-active' : ''} aria-pressed={mode === key} onClick={() => setMode(key)}>
              {candidate.label}
            </button>
          ))}
        </div>
        <Link to={config.to} style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-tertiary)', whiteSpace: 'nowrap' }}>Full board →</Link>
      </div>

      {entries === null && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading…</p>}
      {entries?.length === 0 && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>No players yet.</p>}
      {entries?.length > 0 && displayed.length === 0 && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>No stats yet.</p>}

      {displayed.length > 0 && (
        <div className="jk-vertical-leaderboard" aria-label={`${config.label} leaders`} style={{ gridTemplateColumns: `repeat(${displayed.length}, minmax(0, 1fr))` }}>
          {displayed.map((profile) => {
            const value = profile[config.valueKey];
            const height = maxValue > 0 ? (value / maxValue) * 100 : 0;
            const isCurrentUser = profile.user_id === currentUserId;
            return (
              <Link
                key={profile.user_id}
                to={`/dice/profile/${profile.user_id}`}
                className={`jk-vertical-leader${isCurrentUser ? ' is-current-user' : ''}`}
                aria-label={`Rank ${profile.rank}, ${profile.display_name}, ${value} ${config.label}${isCurrentUser ? ', you' : ''}`}
                title={profile.display_name}
              >
                <span className="jk-vertical-leader-value">{value}</span>
                <span className="jk-vertical-bar-space" aria-hidden="true">
                  <span className={`jk-vertical-bar is-${config.tone}`} style={{ height: `${height}%` }} />
                </span>
                <PlayerAvatar profile={profile} size={30} linkToProfile={false} />
                <span className="jk-vertical-leader-rank">#{profile.rank}{isCurrentUser && ' · You'}</span>
              </Link>
            );
          })}
        </div>
      )}
    </div>
  );
}
