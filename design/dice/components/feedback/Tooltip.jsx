import React from 'react';

export function Tooltip({ children, label, side = 'top' }) {
  const [show, setShow] = React.useState(false);
  const posStyle = {
    top: { bottom: '125%', left: '50%', transform: 'translateX(-50%)' },
    bottom: { top: '125%', left: '50%', transform: 'translateX(-50%)' },
    left: { right: '115%', top: '50%', transform: 'translateY(-50%)' },
    right: { left: '115%', top: '50%', transform: 'translateY(-50%)' },
  }[side];

  return (
    <span
      style={{ position: 'relative', display: 'inline-flex' }}
      onMouseEnter={() => setShow(true)}
      onMouseLeave={() => setShow(false)}
    >
      {children}
      {show && (
        <span
          style={{
            position: 'absolute', ...posStyle,
            background: 'var(--ink-950)', color: 'var(--paper-50)',
            fontFamily: 'var(--font-mono)', fontSize: '11px', textTransform: 'uppercase', letterSpacing: '0.04em',
            padding: '5px 9px', borderRadius: 'var(--radius-sm)', whiteSpace: 'nowrap',
            border: '1px solid rgba(247,241,230,0.12)',
            boxShadow: 'var(--shadow-sm)', zIndex: 10, pointerEvents: 'none',
          }}
        >
          {label}
        </span>
      )}
    </span>
  );
}
