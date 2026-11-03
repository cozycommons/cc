import React from 'react';
import { diceApi } from '../api.js';
import { useDiceResource } from '../resourceCache.js';
import LeaderboardRow from '../components/LeaderboardRow.jsx';
import StatsBackLink from '../components/StatsBackLink.jsx';
import { rankLeaderboard } from '../leaderboard.js';
import LoadingRows from '../components/LoadingRows.jsx';

export default function SelfSinkLeaderboard({ auth }) {
  const [entries] = useDiceResource('self-sinks:500:all', () => diceApi.getSelfSinkLeaderboard(500, false), { fallback: [] });

  const ranked = rankLeaderboard(entries, 'self_sinks');
  const maxValue = ranked[0]?.self_sinks || 0;
  const currentUserId = auth?.profile?.user_id || auth?.user?.id;

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8">
      <StatsBackLink label="Player stats" />
      <p className="jk-display mb-4" style={{ fontSize: 28 }}>Self Sink Leaderboard</p>
      <div className="jk-card overflow-hidden">
        {entries === null && <LoadingRows />}
        {entries?.length === 0 && (
          <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Nobody's self-sunk yet. 🎉</p>
        )}
        {ranked.map((p) => (
          <LeaderboardRow key={p.user_id} rank={p.rank} profile={p} value={p.self_sinks} valueLabel="self-sinks" tied={p.tied} barMode="count" barTone="clay" maxValue={maxValue} isCurrentUser={p.user_id === currentUserId} />
        ))}
      </div>
    </div>
  );
}
