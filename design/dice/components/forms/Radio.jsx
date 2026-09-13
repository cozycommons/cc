import React from 'react';

export function Radio({ label, checked, onChange }) {
  return (
    <label style={{ display: 'inline-flex', alignItems: 'center', gap: '10px', cursor: 'pointer', fontFamily: 'var(--font-body)', fontSize: 'var(--text-body-md)', color: 'var(--text-primary)' }}>
      <span
        onClick={() => onChange && onChange()}
        style={{
          width: 20,
          height: 20,
          borderRadius: '50%',
          border: checked ? '1.5px solid var(--accent-moss)' : '1.5px solid var(--border-default)',
          background: 'var(--surface-card)',
          display: 'inline-flex',
          alignItems: 'center',
          justifyContent: 'center',
          flexShrink: 0,
        }}
      >
        {checked && <span style={{ width: 10, height: 10, borderRadius: '50%', background: 'var(--accent-moss)' }} />}
      </span>
      {label}
    </label>
  );
}
