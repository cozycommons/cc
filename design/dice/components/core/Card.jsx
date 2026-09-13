import React from 'react';

export function Card({ children, padded = true, accent = false, style, className, onClick }) {
  return (
    <div
      className={className}
      onClick={onClick}
      style={{
        background: 'var(--surface-card)',
        border: '1px solid var(--border-subtle)',
        borderRadius: 'var(--radius-lg)',
        boxShadow: accent ? 'var(--glow-accent)' : 'var(--shadow-sm)',
        padding: padded ? 'var(--space-6)' : 0,
        cursor: onClick ? 'pointer' : undefined,
        ...style,
      }}
    >
      {children}
    </div>
  );
}
