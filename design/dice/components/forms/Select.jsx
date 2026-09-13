import React from 'react';

export function Select({ label, value, onChange, options = [] }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', width: '100%' }}>
      {label && (
        <label style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-label-sm)', color: 'var(--text-secondary)' }}>
          {label}
        </label>
      )}
      <select
        value={value}
        onChange={onChange}
        style={{
          fontFamily: 'var(--font-body)',
          fontSize: 'var(--text-body-md)',
          padding: '11px 14px',
          borderRadius: 'var(--radius-md)',
          border: '1.5px solid var(--border-default)',
          background: 'var(--surface-card)',
          color: 'var(--text-primary)',
          appearance: 'none',
          width: '100%',
        }}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>{o.label}</option>
        ))}
      </select>
    </div>
  );
}
