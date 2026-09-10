import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { Input } from '@/components/ui/input';
import { diceApi } from '../api.js';
import LeaderboardRow from '../components/LeaderboardRow.jsx';
import EloDistribution, { summarizeRatings } from '../components/EloDistribution.jsx';
import StatsBackLink from '../components/StatsBackLink.jsx';
import { rankLeaderboard } from '../leaderboard.js';

export default function EloLeaderboard({ auth }) {
  const [entries, setEntries] = useState(null);
  const [query, setQuery] = useState('');

  useEffect(() => {
    diceApi.getEloLeaderboard(500, true).then(setEntries).catch(() => setEntries([]));
  }, []);

  const ranked = rankLeaderboard(entries, 'elo_rating', { provisionalKey: 'is_provisional' });
  const normalizedQuery = query.trim().toLowerCase();
  const displayedEntries = normalizedQuery
    ? ranked.filter((profile) => profile.display_name.toLowerCase().includes(normalizedQuery))
    : ranked;
  const ratingDistribution = summarizeRatings(ranked);
  const eloRange = Math.max(1, ...ranked.filter((profile) => !profile.is_provisional).map((profile) => Math.abs(profile.elo_rating - 1500)));
  const currentUserId = auth?.profile?.user_id || auth?.user?.id;

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8">
      <StatsBackLink label="Player stats" />
      <div className="flex items-center justify-between mb-4">
        <p className="jk-display" style={{ fontSize: 28 }}>ELO Leaderboard</p>
        <Link to="/dice/elo-explained" style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-secondary)' }}>
          How does this work? →
        </Link>
      </div>
      <p className="mb-4" style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-tertiary)' }}>
        Players still in their placement games (first 3 ranked matches) show as unranked until they finish.
      </p>
      <EloDistribution entries={ranked} currentUserId={currentUserId} />
      <Input
        aria-label="Search players"
        placeholder="Search players…"
        value={query}
        onChange={(event) => setQuery(event.target.value)}
        className="mb-4"
      />
      <div className="jk-card overflow-hidden">
        {entries === null && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading…</p>}
        {entries?.length === 0 && (
          <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>No players yet.</p>
        )}
        {entries?.length > 0 && displayedEntries.length === 0 && (
          <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>No players found.</p>
        )}
        {displayedEntries.map((p) => (
          <LeaderboardRow
            key={p.user_id}
            rank={p.rank}
            profile={p}
            value={p.elo_rating}
            valueLabel="ELO"
            unranked={p.is_provisional}
            tied={p.tied}
            barMode="elo"
            maxValue={eloRange}
            isCurrentUser={p.user_id === currentUserId}
          />
        ))}
      </div>
    </div>
  );
}
