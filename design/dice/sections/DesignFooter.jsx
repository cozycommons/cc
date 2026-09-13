import React from 'react';

export function DesignFooter() {
  return (
    <footer style={{ borderTop: '1px solid var(--border-subtle)', marginTop: 'var(--space-16)' }}>
      <div
        style={{
          maxWidth: 'var(--content-max-width)', margin: '0 auto', padding: '32px var(--gutter)',
          display: 'flex', alignItems: 'center', justifyContent: 'space-between', flexWrap: 'wrap', gap: 12,
          fontFamily: 'var(--font-mono)', fontSize: 12, textTransform: 'uppercase', letterSpacing: 'var(--tracking-label)', color: 'var(--text-tertiary)',
        }}
      >
        <span>jasonkeung.com/design — living reference, replaces the static deck</span>
        <div style={{ display: 'flex', gap: 20 }}>
          <a href="/" style={{ color: 'var(--text-secondary)' }}>Home</a>
          <a href="#foundations" style={{ color: 'var(--text-secondary)' }}>Foundations</a>
          <a href="#art" style={{ color: 'var(--text-secondary)' }}>Art</a>
        </div>
      </div>
    </footer>
  );
}
