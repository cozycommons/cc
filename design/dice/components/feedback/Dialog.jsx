import React from 'react';

export function Dialog({ open, onClose, title, children, actions }) {
  if (!open) return null;
  return (
    <div
      onClick={onClose}
      style={{
        position: 'fixed', inset: 0, background: 'rgba(2,2,10,0.45)',
        display: 'flex', alignItems: 'center', justifyContent: 'center', zIndex: 1000,
      }}
    >
      <div
        onClick={(e) => e.stopPropagation()}
        style={{
          background: 'var(--surface-card)',
          borderRadius: 'var(--radius-lg)',
          boxShadow: 'var(--shadow-lg)',
          padding: 'var(--space-8)',
          width: 420,
          maxWidth: '90vw',
        }}
      >
        {title && <h3 style={{ fontSize: '28px', marginBottom: 'var(--space-4)' }}>{title}</h3>}
        <div style={{ fontFamily: 'var(--font-body)', color: 'var(--text-secondary)', marginBottom: 'var(--space-6)' }}>
          {children}
        </div>
        {actions && <div style={{ display: 'flex', gap: 'var(--space-3)', justifyContent: 'flex-end' }}>{actions}</div>}
      </div>
    </div>
  );
}
