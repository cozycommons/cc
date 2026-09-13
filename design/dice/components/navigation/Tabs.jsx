import React from 'react';

export function Tabs({ tabs, active, onChange }) {
  return (
    <div style={{ display: 'flex', gap: 'var(--space-6)', borderBottom: '1.5px solid var(--border-subtle)', overflowX: 'auto' }}>
      {tabs.map((t) => {
        const isActive = t.value === active;
        return (
          <button
            key={t.value}
            onClick={() => onChange(t.value)}
            style={{
              background: 'transparent',
              border: 'none',
              padding: '10px 2px',
              fontFamily: 'var(--font-mono)',
              fontSize: 'var(--text-label-md)',
              textTransform: 'uppercase',
              letterSpacing: 'var(--tracking-label)',
              color: isActive ? 'var(--text-primary)' : 'var(--text-tertiary)',
              borderBottom: isActive ? '2px solid var(--accent-moss)' : '2px solid transparent',
              marginBottom: '-1.5px',
              cursor: 'pointer',
              whiteSpace: 'nowrap',
              transition: 'color var(--duration-fast) var(--ease-standard)',
            }}
          >
            {t.label}
          </button>
        );
      })}
    </div>
  );
}
