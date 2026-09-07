import React, { useMemo, useState } from 'react';
import { Input } from '@/components/ui/input';
import PlayerAvatar from './PlayerAvatar.jsx';

// A searchable "pick someone from the roster" list. `onPick(profile)` fires
// on click; the caller decides what "picking" means (append to a list, fire
// an API call, etc.) and is responsible for updating `excludeIds` afterward
// so the picked entry drops out of the list. `profiles === null` means the
// roster is still loading.
export default function RosterPicker({
  profiles,
  excludeIds = [],
  onPick,
  placeholder = 'Search players, or pick from the list below…',
  emptyRosterMessage = 'No players yet.',
  allTakenMessage = 'Everyone has already been added.',
}) {
  const [query, setQuery] = useState('');
  const loading = profiles === null;

  const options = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (profiles || [])
      .filter((p) => !excludeIds.includes(p.user_id))
      .filter((p) => !q || p.display_name.toLowerCase().includes(q));
  }, [profiles, query, excludeIds]);

  return (
    <div>
      <Input placeholder={placeholder} value={query} onChange={(e) => setQuery(e.target.value)} />
      {/* Always visible (not gated on focus) so an empty search box still
          browses the full player list, not just a handful of suggestions. */}
      <div
        className="mt-1 overflow-y-auto"
        style={{ maxHeight: 320, background: 'var(--surface-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)' }}
      >
        {loading && (
          <p className="px-3 py-2" style={{ fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--text-tertiary)' }}>
            Loading players…
          </p>
        )}
        {!loading && options.length === 0 && (
          <p className="px-3 py-2" style={{ fontFamily: 'var(--font-body)', fontSize: 13, color: 'var(--text-tertiary)' }}>
            {query.trim() ? 'No players found with that name.' : profiles.length === 0 ? emptyRosterMessage : allTakenMessage}
          </p>
        )}
        {options.map((p) => (
          <button
            key={p.user_id}
            type="button"
            onClick={() => {
              onPick(p);
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
