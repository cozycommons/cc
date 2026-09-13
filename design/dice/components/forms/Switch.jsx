import React from 'react';

export function Switch({ checked, onChange, label }) {
  return (
    <label style={{ display: 'inline-flex', alignItems: 'center', gap: '10px', cursor: 'pointer', fontFamily: 'var(--font-body)', fontSize: 'var(--text-body-md)', color: 'var(--text-primary)' }}>
      <span
        onClick={() => onChange && onChange(!checked)}
        style={{
          width: 40,
          height: 22,
          borderRadius: 'var(--radius-pill)',
          background: checked ? 'var(--accent-moss)' : 'var(--neutral-300)',
          position: 'relative',
          transition: 'background var(--duration-base) var(--ease-standard)',
          flexShrink: 0,
        }}
      >
        <span
          style={{
            position: 'absolute',
            top: 2,
            left: checked ? 20 : 2,
            width: 18,
            height: 18,
            borderRadius: '50%',
            background: '#fff',
            boxShadow: 'var(--shadow-xs)',
            transition: 'left var(--duration-base) var(--ease-bounce)',
          }}
        />
      </span>
      {label}
    </label>
  );
}
