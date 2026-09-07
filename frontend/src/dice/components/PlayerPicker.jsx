import React, { useMemo, useState } from 'react';
import { Input } from '@/components/ui/input';
import PlayerAvatar from './PlayerAvatar.jsx';

// Filters the shared `profiles` list (fetched once by the parent form) —
// no per-picker network calls, just client-side filtering as you type.
export default function PlayerPicker({ label, profiles, value, onChange, excludeIds = [] }) {
  const [query, setQuery] = useState('');

  const options = useMemo(() => {
    const q = query.trim().toLowerCase();
    // No cap: with an empty query this is the full player list (the
    // "browse everyone" empty state), not just a handful of suggestions.
    return profiles
      .filter((p) => !excludeIds.includes(p.user_id))
      .filter((p) => !q || p.display_name.toLowerCase().includes(q));
  }, [profiles, query, excludeIds]);

  if (value) {
    return (
      <div>
        <p className="jk-label mb-1">{label}</p>
        <div
          className="flex items-center gap-2 px-3 py-2"
          style={{ border: '1px solid var(--border-default)', borderRadius: 'var(--radius-md)' }}
        >
          <PlayerAvatar profile={value} size={28} linkToProfile={false} />
          <span className="flex-1" style={{ fontFamily: 'var(--font-body)', fontSize: 14 }}>{value.display_name}</span>
          <button
            type="button"
            onClick={() => onChange(null)}
            style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-tertiary)' }}
          >
            change
          </button>
        </div>
      </div>
    );
  }

  return (
    <div>
      <p className="jk-label mb-1">{label}</p>
      <Input
        placeholder="Search players, or pick from the list below…"
        value={query}
        onChange={(e) => setQuery(e.target.value)}
      />
      {/* Always visible (not gated on focus) so an empty search box still
          browses the full player list, not just a handful of suggestions. */}
      <div
        className="mt-1 overflow-y-auto"
        style={{
          maxHeight: 320,
          background: 'var(--surface-card)',
          border: '1px solid var(--border-subtle)',
          borderRadius: 'var(--radius-md)',
        }}
      >
        {options.length === 0 && (
          <p className="px-3 py-2" style={{ fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--text-tertiary)' }}>
            {query.trim() ? 'No players found with that name.' : 'No players yet.'}
          </p>
        )}
        {options.map((p) => (
          <button
            key={p.user_id}
            type="button"
            onClick={() => {
              onChange(p);
              setQuery('');
            }}
            className="w-full flex items-center gap-2 px-3 py-2 text-left"
            style={{ fontFamily: 'var(--font-body)', fontSize: 14, borderBottom: '1px solid var(--border-subtle)' }}
          >
            <PlayerAvatar profile={p} size={24} linkToProfile={false} />
            {p.display_name}
          </button>
        ))}
      </div>
    </div>
  );
}
