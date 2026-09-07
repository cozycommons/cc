import React, { useMemo, useState } from 'react';
import PlayerAvatar from '../components/PlayerAvatar.jsx';

const turnLabelBySlot = ['1st', '2nd', '1st', '2nd'];
const throwOrder = [0, 1, 2, 3];
const slotLabel = (index) => `Team ${index < 2 ? 1 : 2} ${turnLabelBySlot[index]} thrower`;

export default function LiveRosterPicker({ profiles, players, onChange }) {
  const [activeSlot, setActiveSlot] = useState(() => Math.max(0, players.findIndex((player) => !player)));
  const profilesById = useMemo(() => new Map(profiles.map((profile) => [profile.user_id, profile])), [profiles]);

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
  };

  return (
    <div className="grid gap-3 mt-3">
      <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>Each team takes both throws. Pick who goes first.</p>
      {[[0, 1], [2, 3]].map((indexes, teamIndex) => (
        <fieldset
          key={teamIndex}
          className="min-w-0 p-3 rounded-lg border-l-4"
          style={{
            borderLeftColor: `var(--team${teamIndex + 1}-color)`,
            background: `color-mix(in srgb, var(--team${teamIndex + 1}-color) 7%, var(--surface-card))`,
          }}
        >
          <legend className="jk-label px-1">TEAM {teamIndex + 1}</legend>
          <div className="grid grid-cols-2 gap-2">
            {indexes.map((index) => {
              const profile = profilesById.get(players[index]);
              const active = activeSlot === index;
              return (
                <button
                  key={index}
                  type="button"
                  aria-pressed={active}
                  aria-label={`${slotLabel(index)}: ${profile?.display_name || 'Choose'}`}
                  onClick={() => setActiveSlot(index)}
                  className="min-w-0 min-h-14 p-2 rounded-md text-left flex items-center gap-2 overflow-hidden transition-all duration-200"
                  style={{
                    border: `1.5px solid ${active ? `var(--team${teamIndex + 1}-color)` : 'var(--border-subtle)'}`,
                    background: 'var(--surface-card)',
                  }}
                >
                  {profile ? <PlayerAvatar profile={profile} size={36} linkToProfile={false} /> : (
                    <span className="w-9 h-9 rounded-full grid place-items-center text-lg" style={{ background: 'var(--surface-sunken)', color: 'var(--text-tertiary)' }}>+</span>
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

      <div className="grid grid-cols-2 gap-2 max-h-56 overflow-y-auto" aria-label={`Players for ${slotLabel(activeSlot)}`}>
        {profiles.map((profile) => {
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
              <span className="min-w-0 font-semibold truncate">{profile.display_name.split(' ')[0]}</span>
            </button>
          );
        })}
      </div>
    </div>
  );
}
