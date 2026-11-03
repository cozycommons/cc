import React from 'react';
import { diceApi } from '../api.js';
import { useDiceResource } from '../resourceCache.js';
import GameRow from '../components/GameRow.jsx';
import LoadingRows from '../components/LoadingRows.jsx';

export default function MatchHistory() {
  const [games] = useDiceResource('games:200:0', () => diceApi.getGames(200, 0), { fallback: [] });

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8">
      <p className="jk-display mb-4" style={{ fontSize: 28 }}>Match History</p>
      <div className="jk-card overflow-hidden">
        {games === null && <LoadingRows />}
        {games?.length === 0 && (
          <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>No matches logged yet.</p>
        )}
        {games?.map((g) => <GameRow key={g.id} game={g} />)}
      </div>
    </div>
  );
}
