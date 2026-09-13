import React from 'react';

export function Checkbox({ label, checked, onChange }) {
  return (
    <label style={{ display: 'inline-flex', alignItems: 'center', gap: '10px', cursor: 'pointer', fontFamily: 'var(--font-body)', fontSize: 'var(--text-body-md)', color: 'var(--text-primary)' }}>
      <span
        onClick={() => onChange && onChange(!checked)}
        style={{
          width: 20,
          height: 20,
          borderRadius: 'var(--radius-sm)',
          border: checked ? '1.5px solid var(--accent-moss)' : '1.5px solid var(--border-default)',
          background: checked ? 'var(--accent-moss)' : 'var(--surface-card)',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          transition: 'all var(--duration-fast) var(--ease-standard)',
          flexShrink: 0,
        }}
      >
        {checked && (
          <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="3">
            <path d="M20 6L9 17l-5-5" />
          </svg>
        )}
      </span>
      {label}
    </label>
  );
}
