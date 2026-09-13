import React from 'react';

const accentColors = {
  moss: 'var(--accent-moss)',
  clay: 'var(--accent-clay)',
  sky: 'var(--accent-sky)',
  blossom: 'var(--accent-blossom)',
  gold: 'var(--accent-gold)',
  berry: 'var(--accent-berry)',
  neutral: 'var(--neutral-700)',
};

export function Badge({ children, color = 'moss' }) {
  const c = accentColors[color] || accentColors.moss;
  const isLight = color === 'blossom' || color === 'gold';
  return (
    <span
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: '6px',
        padding: '4px 10px',
        borderRadius: 'var(--radius-pill)',
        background: c,
        color: isLight ? 'var(--ink-950)' : '#fff',
        fontFamily: 'var(--font-mono)',
        fontSize: 'var(--text-label-xs)',
        textTransform: 'uppercase',
        letterSpacing: 'var(--tracking-label)',
        whiteSpace: 'nowrap',
      }}
    >
      {children}
    </span>
  );
}
