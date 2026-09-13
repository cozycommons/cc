import React from 'react';

export function Input({ label, placeholder, value, onChange, type = 'text', error, helper }) {
  const [focus, setFocus] = React.useState(false);
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: '6px', width: '100%' }}>
      {label && (
        <label style={{ fontFamily: 'var(--font-mono)', fontSize: 'var(--text-label-sm)', color: 'var(--text-secondary)' }}>
          {label}
        </label>
      )}
      <input
        type={type}
        placeholder={placeholder}
        value={value}
        onChange={onChange}
        onFocus={() => setFocus(true)}
        onBlur={() => setFocus(false)}
        style={{
          fontFamily: 'var(--font-body)',
          fontSize: 'var(--text-body-md)',
          padding: '11px 14px',
          borderRadius: 'var(--radius-md)',
          border: error ? '1.5px solid var(--state-danger)' : focus ? '1.5px solid var(--focus-ring)' : '1.5px solid var(--border-default)',
          outline: 'none',
          background: 'var(--surface-card)',
          color: 'var(--text-primary)',
          transition: 'border var(--duration-fast) var(--ease-standard)',
          width: '100%',
        }}
      />
      {(helper || error) && (
        <span style={{ fontFamily: 'var(--font-body)', fontSize: '12px', color: error ? 'var(--state-danger)' : 'var(--text-tertiary)' }}>
          {error || helper}
        </span>
      )}
    </div>
  );
}
