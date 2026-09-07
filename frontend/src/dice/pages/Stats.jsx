import React, { useEffect, useState } from 'react';
import { diceApi } from '../api.js';
import { usePageviewTracking } from '../../analytics/usePageviewTracking';
import { CurrentStreaksSection, HistoricalRecordsSection } from './Home.jsx';

export default function Stats() {
  const [games, setGames] = useState(null);
  usePageviewTracking('dice', 'stats', '/dice/stats');

  useEffect(() => {
    diceApi.getGames(500).then(setGames).catch(() => setGames([]));
  }, []);

  return (
    <main className="max-w-2xl mx-auto px-4 sm:px-6 py-8">
      <div className="mb-8">
        <p className="jk-label">// DICE STATS</p>
        <h1 className="jk-display text-4xl mt-1">Stats</h1>
      </div>
      {games === null && <div className="jk-card p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading stats…</div>}
      <CurrentStreaksSection games={games} limit={Number.POSITIVE_INFINITY} viewAllTo={null} />
      <HistoricalRecordsSection games={games} />
      {games?.length === 0 && <div className="jk-card p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Play a few matches to start building records.</div>}
    </main>
  );
}
