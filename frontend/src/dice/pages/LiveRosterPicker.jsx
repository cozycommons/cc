import React, { useMemo, useRef, useState } from 'react';
import { Input } from '@/components/ui/input';
import PlayerAvatar from '../components/PlayerAvatar.jsx';

const turnLabelBySlot = ['1st', '2nd', '1st', '2nd'];
const throwOrder = [0, 1, 2, 3];
const slotLabel = (index) => `Team ${index < 2 ? 1 : 2} ${turnLabelBySlot[index]} thrower`;

export default function LiveRosterPicker({ profiles, players, onChange }) {
  const [activeSlot, setActiveSlot] = useState(() => Math.max(0, players.findIndex((player) => !player)));
  const [query, setQuery] = useState('');
  const searchRef = useRef(null);
  const profilesById = useMemo(() => new Map(profiles.map((profile) => [profile.user_id, profile])), [profiles]);
  const matches = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase();
    const filtered = normalized
      ? profiles.filter((profile) => profile.display_name.toLocaleLowerCase().includes(normalized))
      : profiles;
    return filtered.slice(0, 6);
  }, [profiles, query]);

  const pick = (playerId) => {
    const occupiedSlot = players.indexOf(playerId);
    const replacedPlayer = players[activeSlot];
    onChange(players.map((current, index) => {
      if (index === activeSlot) return playerId;
      if (index === occupiedSlot) return replacedPlayer;
      return current;
    }));
    const nextEmpty = players.findIndex((current, index) => index !== activeSlot && !current);
    setActiveSlot(nextEmpty >= 0 ? nextEmpty : (activeSlot + 1) % players.length);
    setQuery('');
    searchRef.current?.focus();
  };

  const activateSlot = (index) => {
    setActiveSlot(index);
    setQuery('');
    requestAnimationFrame(() => searchRef.current?.focus());
  };

  return (
    <div className="grid gap-5 mt-5">
      <p className="text-sm leading-6" style={{ color: 'var(--text-secondary)' }}>Each team takes both throws. Tap a spot, then find the player.</p>
      {[[0, 1], [2, 3]].map((indexes, teamIndex) => (
        <fieldset
          key={teamIndex}
          className="min-w-0 p-3 min-[360px]:p-4 rounded-xl border-l-4"
          style={{
            borderLeftColor: `var(--team${teamIndex + 1}-color)`,
            background: `color-mix(in srgb, var(--team${teamIndex + 1}-color) 7%, var(--surface-card))`,
          }}
        >
          <legend className="jk-label px-1">TEAM {teamIndex + 1}</legend>
          <div className="grid grid-cols-2 gap-2 min-[360px]:gap-3">
            {indexes.map((index) => {
              const profile = profilesById.get(players[index]);
              const active = activeSlot === index;
              return (
                <button
                  key={index}
                  type="button"
                  aria-pressed={active}
                  aria-label={`${slotLabel(index)}: ${profile?.display_name || 'Choose'}`}
                  onClick={() => activateSlot(index)}
                  className="min-w-0 min-h-16 p-2 min-[360px]:p-2.5 rounded-lg text-left flex items-center gap-2 overflow-hidden transition-all duration-200"
                  style={{
                    border: `1.5px solid ${active ? `var(--team${teamIndex + 1}-color)` : 'var(--border-subtle)'}`,
                    background: 'var(--surface-card)',
                  }}
                >
                  {profile ? (
                    <span className="hidden min-[360px]:inline-flex shrink-0"><PlayerAvatar profile={profile} size={32} linkToProfile={false} /></span>
                  ) : (
                    <span className="hidden min-[360px]:grid w-8 h-8 shrink-0 rounded-full place-items-center text-lg" style={{ background: 'var(--surface-sunken)', color: 'var(--text-tertiary)' }}>+</span>
                  )}
                  <span className="min-w-0">
                    <span className="jk-label block">THROWS {turnLabelBySlot[index]}</span>
                    <span className="font-semibold block truncate">{profile?.display_name?.split(' ')[0] || 'Choose'}</span>
                  </span>
                </button>
              );
            })}
          </div>
        </fieldset>
      ))}

      {players.every(Boolean) && (
        <section
          className="min-w-0 p-3 rounded-lg"
          aria-label="Throw order"
          aria-live="polite"
          style={{ background: 'var(--surface-sunken)' }}
        >
          <p className="jk-label">ROUND ORDER</p>
          <div className="grid grid-cols-4 gap-1 mt-2" role="list">
            {throwOrder.map((slotIndex, turnIndex) => {
              const profile = profilesById.get(players[slotIndex]);
              return (
                <div key={slotIndex} className="min-w-0 text-center" role="listitem" aria-label={`${turnIndex + 1}: ${profile?.display_name}`}>
                  <span className="jk-label block">{turnIndex + 1}</span>
                  <span className="inline-block mt-1">
                    <PlayerAvatar profile={profile} size={30} linkToProfile={false} />
                  </span>
                  <span className="block truncate text-xs font-semibold mt-1">{profile?.display_name?.split(' ')[0]}</span>
                </div>
              );
            })}
          </div>
        </section>
      )}

      <section className="min-w-0" aria-label={`Players for ${slotLabel(activeSlot)}`}>
        <label htmlFor="live-player-search" className="jk-label block mb-2">
          FIND {slotLabel(activeSlot).toUpperCase()}
        </label>
        <Input
          ref={searchRef}
          id="live-player-search"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          placeholder="Search players by name"
          autoComplete="off"
          className="min-h-12"
        />
        <div className="grid grid-cols-2 gap-2 mt-3">
        {matches.map((profile) => {
          const selectedHere = players[activeSlot] === profile.user_id;
          return (
            <button
              key={profile.user_id}
              type="button"
              aria-pressed={selectedHere}
              onClick={() => pick(profile.user_id)}
              className="min-w-0 min-h-12 p-2 rounded-md text-left flex items-center gap-2 overflow-hidden transition-all duration-200"
              style={{
                border: `1px solid ${selectedHere ? 'var(--surface-strong)' : 'var(--border-subtle)'}`,
                background: selectedHere ? 'var(--surface-sunken)' : 'var(--surface-card)',
              }}
            >
              <PlayerAvatar profile={profile} size={34} linkToProfile={false} />
              <span className="min-w-0 font-semibold truncate">{profile.display_name}</span>
            </button>
          );
        })}
        </div>
        {matches.length === 0 && query && (
          <p className="py-5 text-center text-sm" role="status" style={{ color: 'var(--text-secondary)' }}>No players match “{query}”.</p>
        )}
        {!query && profiles.length > matches.length && (
          <p className="mt-3 text-center text-xs" style={{ color: 'var(--text-tertiary)' }}>Search to find {profiles.length - matches.length} more players.</p>
        )}
      </section>
    </div>
  );
}
