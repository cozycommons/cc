import React, { useEffect, useState } from 'react';
import { diceApi } from '../api.js';
import LeaderboardRow from '../components/LeaderboardRow.jsx';
import { rankLeaderboard } from '../leaderboard.js';

export default function SelfSinkLeaderboard({ auth }) {
  const [entries, setEntries] = useState(null);
  const experimentalEnabled = auth?.features?.dice_live_referee?.effective === true;

  useEffect(() => {
    diceApi.getSelfSinkLeaderboard(500, !experimentalEnabled).then(setEntries).catch(() => setEntries([]));
  }, [experimentalEnabled]);

  const ranked = experimentalEnabled
    ? rankLeaderboard(entries, 'self_sinks')
    : (entries || []).map((profile, index) => ({ ...profile, rank: index + 1 }));
  const maxValue = ranked[0]?.self_sinks || 0;
  const currentUserId = auth?.profile?.user_id || auth?.user?.id;

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8">
      <p className="jk-display mb-4" style={{ fontSize: 28 }}>Self Sink Leaderboard</p>
      <div className="jk-card overflow-hidden">
        {entries === null && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading…</p>}
        {entries?.length === 0 && (
          <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Nobody's self-sunk yet. 🎉</p>
        )}
        {ranked.map((p) => (
          <LeaderboardRow key={p.user_id} rank={p.rank} profile={p} value={p.self_sinks} valueLabel={experimentalEnabled ? 'self-sinks' : 'sinks'} barMode={experimentalEnabled ? 'count' : undefined} barTone="clay" maxValue={maxValue} isCurrentUser={experimentalEnabled && p.user_id === currentUserId} />
        ))}
      </div>
    </div>
  );
}
