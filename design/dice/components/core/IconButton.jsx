import React from 'react';

const sizes = { sm: 32, md: 40, lg: 48 };

export function IconButton({ children, size = 'md', variant = 'ghost', disabled = false, onClick, label }) {
  const [hover, setHover] = React.useState(false);
  const d = sizes[size] || sizes.md;
  const isSolid = variant === 'solid';
  return (
    <button
      aria-label={label}
      title={label}
      disabled={disabled}
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => setHover(false)}
      style={{
        width: d,
        height: d,
        borderRadius: 'var(--radius-md)',
        border: isSolid ? '1.5px solid var(--surface-strong)' : '1.5px solid var(--border-default)',
        background: isSolid ? (hover ? 'var(--surface-strong-hover)' : 'var(--surface-strong)') : (hover ? 'var(--surface-sunken)' : 'transparent'),
        color: isSolid ? 'var(--text-on-strong)' : 'var(--text-primary)',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.45 : 1,
        transition: 'background var(--duration-fast) var(--ease-standard)',
        flexShrink: 0,
      }}
    >
      {children}
    </button>
  );
}
