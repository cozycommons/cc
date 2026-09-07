import React, { useEffect, useMemo, useState } from 'react';
import { Link } from 'react-router-dom';
import { Input } from '@/components/ui/input';
import { diceApi } from '../api.js';
import PlayerAvatar from '../components/PlayerAvatar.jsx';

function PlayerListRow({ profile }) {
  return (
    <Link
      to={`/dice/profile/${profile.user_id}`}
      className="jk-row flex items-center gap-3 px-4 py-2.5"
      style={{ borderBottom: '1px solid var(--border-subtle)' }}
    >
      <PlayerAvatar profile={profile} size={36} linkToProfile={false} />
      <div className="flex-1 min-w-0 flex items-center gap-1.5">
        <span
          className="truncate"
          style={{ fontFamily: 'var(--font-body)', fontWeight: 500, fontSize: 14, color: 'var(--text-primary)' }}
        >
          {profile.display_name}
        </span>
        {profile.is_provisional && (
          <span
            style={{
              fontFamily: 'var(--font-mono)',
              fontSize: 9,
              fontWeight: 600,
              color: 'var(--text-on-strong)',
              background: 'var(--surface-strong)',
              borderRadius: 3,
              padding: '1px 5px',
              letterSpacing: '0.03em',
              whiteSpace: 'nowrap',
              flexShrink: 0,
            }}
          >
            PROVISIONAL
          </span>
        )}
      </div>
      <div className="flex-shrink-0 text-right" style={{ fontFamily: 'var(--font-mono)' }}>
        <div style={{ fontSize: 14, color: 'var(--text-primary)' }}>
          {profile.elo_rating}
          <span style={{ fontSize: 11, color: 'var(--text-tertiary)', marginLeft: 4 }}>ELO</span>
        </div>
        <div style={{ fontSize: 11, color: 'var(--text-tertiary)', marginTop: 2 }}>
          {profile.ranked_wins}-{profile.ranked_losses} ranked &middot; {profile.games_played} games
        </div>
      </div>
    </Link>
  );
}

export default function Players() {
  const [profiles, setProfiles] = useState(null);
  const [query, setQuery] = useState('');

  useEffect(() => {
    diceApi.searchProfiles('', 500).then(setProfiles).catch(() => setProfiles([]));
  }, []);

  const filtered = useMemo(() => {
    if (!profiles) return null;
    const q = query.trim().toLowerCase();
    return q ? profiles.filter((p) => p.display_name.toLowerCase().includes(q)) : profiles;
  }, [profiles, query]);

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8">
      <p className="jk-display mb-4" style={{ fontSize: 28 }}>Players</p>
      <Input
        placeholder="Search players…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
        className="mb-4"
      />
      <div className="jk-card overflow-hidden">
        {filtered === null && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading…</p>}
        {filtered?.length === 0 && (
          <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>
            {query.trim() ? 'No players found.' : 'No players yet.'}
          </p>
        )}
        {filtered?.map((p) => <PlayerListRow key={p.user_id} profile={p} />)}
      </div>
    </div>
  );
}
