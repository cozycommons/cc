import React, { useEffect, useState } from 'react';
import { diceApi } from '../api.js';
import GameRow from '../components/GameRow.jsx';

export default function MatchHistory() {
  const [games, setGames] = useState(null);

  useEffect(() => {
    diceApi.getGames(200, 0).then(setGames).catch(() => setGames([]));
  }, []);

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8">
      <p className="jk-display mb-4" style={{ fontSize: 28 }}>Match History</p>
      <div className="jk-card overflow-hidden">
        {games === null && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading…</p>}
        {games?.length === 0 && (
          <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>No matches logged yet.</p>
        )}
        {games?.map((g) => <GameRow key={g.id} game={g} />)}
      </div>
    </div>
  );
}
