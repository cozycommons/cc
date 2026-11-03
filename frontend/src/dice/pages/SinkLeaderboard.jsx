import React from 'react';
import { diceApi } from '../api.js';
import { useDiceResource } from '../resourceCache.js';
import LeaderboardRow from '../components/LeaderboardRow.jsx';
import StatsBackLink from '../components/StatsBackLink.jsx';
import { rankLeaderboard } from '../leaderboard.js';
import LoadingRows from '../components/LoadingRows.jsx';

export default function SinkLeaderboard({ auth }) {
  const [entries] = useDiceResource('sinks:500:all', () => diceApi.getSinkLeaderboard(500, false), { fallback: [] });

  const ranked = rankLeaderboard(entries, 'sinks');
  const maxValue = ranked[0]?.sinks || 0;
  const currentUserId = auth?.profile?.user_id || auth?.user?.id;

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8">
      <StatsBackLink label="Player stats" />
      <p className="jk-display mb-4" style={{ fontSize: 28 }}>Sink Leaderboard</p>
      <div className="jk-card overflow-hidden">
        {entries === null && <LoadingRows />}
        {entries?.length === 0 && (
          <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Nobody's sunk anything yet.</p>
        )}
        {ranked.map((p) => (
          <LeaderboardRow key={p.user_id} rank={p.rank} profile={p} value={p.sinks} valueLabel="sinks" tied={p.tied} barMode="count" maxValue={maxValue} isCurrentUser={p.user_id === currentUserId} />
        ))}
      </div>
    </div>
  );
}
