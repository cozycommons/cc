import React from 'react';
import { SceneWindow } from '../components/decor/SceneWindow';
import { HouseIcon } from '../components/decor/icons';

const ACCENT_STRIP = [
  { name: 'Moss', v: 'var(--accent-moss)' },
  { name: 'Clay', v: 'var(--accent-clay)' },
  { name: 'Sky', v: 'var(--accent-sky)' },
  { name: 'Blossom', v: 'var(--accent-blossom)' },
  { name: 'Gold', v: 'var(--accent-gold)' },
  { name: 'Berry', v: 'var(--accent-berry)' },
];

export function Hero() {
  return (
    <section className="ds-fade-up" style={{ maxWidth: 'var(--content-max-width)', margin: '0 auto', padding: '64px var(--gutter) 0' }}>
      <div style={{ display: 'flex', gap: '56px', flexWrap: 'wrap', alignItems: 'center' }}>
        <div style={{ flex: '1 1 480px', minWidth: 0 }}>
          <span className="ds-eyebrow" style={{ color: 'var(--accent-moss)' }}>// Personal brand — living reference</span>
          <h1 style={{ fontSize: 'clamp(44px, 6.4vw, 88px)', margin: '18px 0 22px', maxWidth: 640 }}>
            The Jason Keung<br />Design System
          </h1>
          <p style={{ fontSize: 'var(--text-body-lg)', color: 'var(--text-secondary)', maxWidth: 520, lineHeight: 'var(--leading-relaxed)', marginBottom: 'var(--space-8)' }}>
            Tokens, primitives, and prototypes for a warm-neutral base with small,
            deliberate pops of color — built from a cozy farm mood board and
            kept honest to one rule: color shows up in windows, not whole screens.
          </p>
          <div style={{ display: 'flex', gap: '14px', flexWrap: 'wrap', marginBottom: 'var(--space-10)' }}>
            <a href="#components">
              <button
                style={{
                  fontFamily: 'var(--font-body)', fontWeight: 600, fontSize: '15px',
                  padding: '13px 26px', borderRadius: 'var(--radius-md)',
                  background: 'var(--accent-moss)', color: '#fff', border: '1.5px solid var(--accent-moss)', cursor: 'pointer',
                }}
              >
                Browse components
              </button>
            </a>
            <a href="#art">
              <button
                style={{
                  fontFamily: 'var(--font-body)', fontWeight: 600, fontSize: '15px',
                  padding: '13px 26px', borderRadius: 'var(--radius-md)',
                  background: 'transparent', color: 'var(--text-primary)', border: '1.5px solid var(--border-default)', cursor: 'pointer',
                }}
              >
                See the art gallery
              </button>
            </a>
          </div>

          <div style={{ display: 'flex', gap: '8px' }}>
            {ACCENT_STRIP.map((a) => (
              <div key={a.name} title={a.name} style={{ flex: 1, height: 8, borderRadius: 'var(--radius-pill)', background: a.v }} />
            ))}
          </div>
        </div>

        <div style={{ flex: '1 1 340px', minWidth: 280, maxWidth: 460 }}>
          <SceneWindow icon={HouseIcon} mood="dusk" label="Reference mood" sublabel="Farmhouse, lantern light, cedar roof" aspect="5 / 4" iconSize={72} style={{ boxShadow: 'var(--glow-accent)', borderStyle: 'solid' }} />
        </div>
      </div>
    </section>
  );
}
