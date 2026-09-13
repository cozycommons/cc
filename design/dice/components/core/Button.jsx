import React from 'react';

const sizeStyles = {
  sm: { padding: '8px 16px', fontSize: '14px' },
  md: { padding: '11px 22px', fontSize: '15px' },
  lg: { padding: '14px 28px', fontSize: '16px' },
};

const variantStyles = {
  primary: {
    background: 'var(--surface-strong)',
    color: 'var(--text-on-strong)',
    border: '1.5px solid var(--surface-strong)',
  },
  accent: {
    background: 'var(--accent-moss)',
    color: '#fff',
    border: '1.5px solid var(--accent-moss)',
  },
  secondary: {
    background: 'transparent',
    color: 'var(--text-primary)',
    border: '1.5px solid var(--border-default)',
  },
  ghost: {
    background: 'transparent',
    color: 'var(--text-primary)',
    border: '1.5px solid transparent',
  },
  danger: {
    background: 'var(--state-danger)',
    color: '#fff',
    border: '1.5px solid var(--state-danger)',
  },
};

export function Button({
  children,
  variant = 'primary',
  size = 'md',
  disabled = false,
  onClick,
  type = 'button',
  style,
}) {
  const [hover, setHover] = React.useState(false);
  const [active, setActive] = React.useState(false);

  const base = variantStyles[variant] || variantStyles.primary;
  const sz = sizeStyles[size] || sizeStyles.md;

  let bg = base.background;
  if (!disabled && hover) {
    if (variant === 'primary') bg = 'var(--surface-strong-hover)';
    else if (variant === 'accent') bg = 'var(--accent-moss-deep)';
    else if (variant === 'secondary') bg = 'var(--surface-sunken)';
    else if (variant === 'ghost') bg = 'var(--surface-sunken)';
    else if (variant === 'danger') bg = 'var(--accent-clay-deep)';
  }

  return (
    <button
      type={type}
      disabled={disabled}
      onClick={onClick}
      onMouseEnter={() => setHover(true)}
      onMouseLeave={() => { setHover(false); setActive(false); }}
      onMouseDown={() => setActive(true)}
      onMouseUp={() => setActive(false)}
      style={{
        fontFamily: 'var(--font-body)',
        fontWeight: 600,
        borderRadius: 'var(--radius-md)',
        cursor: disabled ? 'not-allowed' : 'pointer',
        opacity: disabled ? 0.45 : 1,
        transition: 'background var(--duration-fast) var(--ease-standard), transform var(--duration-fast) var(--ease-standard)',
        transform: active && !disabled ? 'scale(0.98)' : 'scale(1)',
        display: 'inline-flex',
        alignItems: 'center',
        justifyContent: 'center',
        gap: '8px',
        ...base,
        ...sz,
        background: bg,
        ...style,
      }}
    >
      {children}
    </button>
  );
}
