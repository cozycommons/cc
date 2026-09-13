import React from 'react';

export function Tag({ children, active = false, onClick }) {
  return (
    <button
      onClick={onClick}
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 'var(--text-label-sm)',
        textTransform: 'uppercase',
        letterSpacing: 'var(--tracking-label)',
        padding: '6px 12px',
        borderRadius: 'var(--radius-pill)',
        border: active ? '1.5px solid var(--surface-strong)' : '1.5px solid var(--border-default)',
        background: active ? 'var(--surface-strong)' : 'transparent',
        color: active ? 'var(--text-on-strong)' : 'var(--text-secondary)',
        cursor: onClick ? 'pointer' : 'default',
        transition: 'all var(--duration-fast) var(--ease-standard)',
      }}
    >
      {children}
    </button>
  );
}
