import React from 'react';

/* A "window into the game world" placeholder frame — used both as hero
   decoration and as reserved slots for the real farm/nature art.
   Renders a soft mood gradient + a horizon line + a centered scenery icon,
   so an empty slot still reads as an intentional, branded panel rather
   than a blank box. Swap in a real image via the `src` prop once art
   exists — see art/manifest.js. */

const MOODS = {
  dusk: ['var(--accent-gold)', 'var(--accent-clay-deep)'],
  meadow: ['var(--accent-moss)', 'var(--ink-950)'],
  sky: ['var(--accent-sky)', 'var(--accent-blossom-deep)'],
  night: ['var(--accent-sky-deep)', 'var(--ink-950)'],
  blossom: ['var(--accent-blossom)', 'var(--accent-sky-deep)'],
};

export function SceneWindow({
  icon: Icon,
  mood = 'dusk',
  label,
  sublabel,
  src,
  aspect = '4 / 3',
  iconSize = 56,
  style,
}) {
  const [from, to] = MOODS[mood] || MOODS.dusk;

  return (
    <div className="ds-window" style={{ aspectRatio: aspect, ...style }}>
      {src ? (
        <img
          src={src}
          alt={label || ''}
          style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', objectFit: 'cover' }}
        />
      ) : (
        <div
          style={{
            position: 'absolute',
            inset: 0,
            background: `linear-gradient(165deg, ${from} 0%, ${to} 130%)`,
          }}
        >
          <svg
            viewBox="0 0 100 60"
            preserveAspectRatio="none"
            style={{ position: 'absolute', left: 0, right: 0, bottom: 0, width: '100%', height: '46%' }}
          >
            <path d="M0,38 Q25,22 50,32 T100,26 L100,60 L0,60 Z" fill="rgba(2,2,10,0.22)" />
            <path d="M0,48 Q30,36 60,42 T100,40 L100,60 L0,60 Z" fill="rgba(2,2,10,0.38)" />
          </svg>
          {Icon && (
            <div
              style={{
                position: 'absolute',
                inset: 0,
                display: 'flex',
                alignItems: 'center',
                justifyContent: 'center',
                color: 'rgba(247,241,230,0.88)',
                filter: 'drop-shadow(0 2px 8px rgba(2,2,10,0.25))',
              }}
            >
              <Icon size={iconSize} strokeWidth={1.3} />
            </div>
          )}
        </div>
      )}
      {(label || sublabel) && (
        <div className="ds-window-label">
          {label && <div>{label}</div>}
          {sublabel && <div style={{ opacity: 0.72, marginTop: 2, letterSpacing: 0 }}>{sublabel}</div>}
        </div>
      )}
    </div>
  );
}
