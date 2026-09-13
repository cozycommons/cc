import React from 'react';

const accentColors = {
  moss: 'var(--accent-moss)',
  gold: 'var(--accent-gold)',
  berry: 'var(--state-danger)',
  sky: 'var(--accent-sky)',
};

export function Toast({ message, tone = 'moss', onDismiss }) {
  return (
    <div
      style={{
        display: 'flex', alignItems: 'center', gap: '12px',
        background: 'var(--ink-950)', color: 'var(--paper-50)',
        borderRadius: 'var(--radius-md)', padding: '12px 16px',
        boxShadow: 'var(--shadow-md)', fontFamily: 'var(--font-body)', fontSize: '14px',
        border: '1px solid rgba(247,241,230,0.12)',
        borderLeft: `3px solid ${accentColors[tone] || accentColors.moss}`,
        maxWidth: 360,
      }}
    >
      <span style={{ flex: 1 }}>{message}</span>
      {onDismiss && (
        <button onClick={onDismiss} style={{ background: 'transparent', border: 'none', color: 'var(--neutral-400)', cursor: 'pointer', fontSize: 16, lineHeight: 1 }}>×</button>
      )}
    </div>
  );
}
