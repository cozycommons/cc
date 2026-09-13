import React from 'react';

const NEUTRALS = [
  ['--ink-950', '#02020A'], ['--neutral-900', '#131019'], ['--neutral-800', '#211D28'],
  ['--neutral-700', '#3A3542'], ['--neutral-600', '#58525C'], ['--neutral-500', '#7A7480'],
  ['--neutral-400', '#A39CA0'], ['--neutral-300', '#C9C0B4'], ['--neutral-200', '#E2D9C8'],
  ['--neutral-100', '#EEE7D8'], ['--paper-50', '#F9F4EC'], ['--neutral-50', '#FBF8F1'],
];

const ACCENTS_LIGHT_DARK = [
  { name: 'Moss', var: '--accent-moss', hex: '#4F7942', deep: '--accent-moss-deep' },
  { name: 'Clay', var: '--accent-clay', hex: '#B0512E', deep: '--accent-clay-deep' },
  { name: 'Sky', var: '--accent-sky', hex: '#5C82B0', deep: '--accent-sky-deep' },
  { name: 'Blossom', var: '--accent-blossom', hex: '#E2A0C4', deep: '--accent-blossom-deep' },
  { name: 'Gold', var: '--accent-gold', hex: '#E3AE3F', deep: '--accent-gold-deep' },
  { name: 'Berry', var: '--accent-berry', hex: '#9C3B3B', deep: null },
];

const ACCENTS_JAYCEE = [
  { name: 'Moss', var: '--accent-moss', hex: '#E31C79', deep: '--accent-moss-deep' },
  { name: 'Clay', var: '--accent-clay', hex: '#9D5FD1', deep: '--accent-clay-deep' },
  { name: 'Sky', var: '--accent-sky', hex: '#B47AE0', deep: '--accent-sky-deep' },
  { name: 'Blossom', var: '--accent-blossom', hex: '#F5A0D4', deep: '--accent-blossom-deep' },
  { name: 'Gold', var: '--accent-gold', hex: '#E85C9A', deep: '--accent-gold-deep' },
  { name: 'Berry', var: '--accent-berry', hex: '#A81155', deep: null },
];

const SEMANTIC = [
  { label: 'surface-page', v: 'var(--surface-page)', text: 'var(--text-primary)', border: true },
  { label: 'surface-card', v: 'var(--surface-card)', text: 'var(--text-primary)', border: true },
  { label: 'surface-sunken', v: 'var(--surface-sunken)', text: 'var(--text-primary)', border: true },
  { label: 'surface-inverse', v: 'var(--surface-inverse)', text: 'var(--text-inverse)' },
  { label: 'state-success', v: 'var(--state-success)', text: '#fff' },
  { label: 'state-warning', v: 'var(--state-warning)', text: 'var(--ink-950)' },
  { label: 'state-danger', v: 'var(--state-danger)', text: '#fff' },
  { label: 'state-info', v: 'var(--state-info)', text: '#fff' },
];

const TYPE_SCALE = [
  ['Display XL', 'var(--text-display-xl)', '96px'],
  ['Display LG', 'var(--text-display-lg)', '72px'],
  ['Display MD', 'var(--text-display-md)', '56px'],
  ['Display SM', 'var(--text-display-sm)', '40px'],
  ['Display XS', 'var(--text-display-xs)', '28px'],
];

const SPACING = ['1', '2', '3', '4', '5', '6', '8', '10', '12', '16', '20', '24', '32'];

const RADII = [
  ['sm', 'var(--radius-sm)', '4px'], ['md', 'var(--radius-md)', '8px'],
  ['lg', 'var(--radius-lg)', '14px'], ['xl', 'var(--radius-xl)', '20px'],
  ['pill', 'var(--radius-pill)', '999px'],
];

const SHADOWS = [
  ['xs', 'var(--shadow-xs)'], ['sm', 'var(--shadow-sm)'],
  ['md', 'var(--shadow-md)'], ['lg', 'var(--shadow-lg)'],
];

function SectionHeader({ index, title, desc }) {
  return (
    <div style={{ marginBottom: 'var(--space-10)' }}>
      <span className="ds-eyebrow" style={{ color: 'var(--accent-clay)' }}>{`// ${index} — Foundations`}</span>
      <h2 style={{ margin: '14px 0 10px' }}>{title}</h2>
      {desc && <p style={{ color: 'var(--text-secondary)', maxWidth: 620, fontSize: 'var(--text-body-md)' }}>{desc}</p>}
    </div>
  );
}

function SubLabel({ children }) {
  return (
    <p className="ds-eyebrow" style={{ marginBottom: 'var(--space-4)', color: 'var(--text-tertiary)' }}>{children}</p>
  );
}

export function Foundations({ theme }) {
  const [bounce, setBounce] = React.useState(false);
  const ACCENTS = theme === 'jaycee' ? ACCENTS_JAYCEE : ACCENTS_LIGHT_DARK;
  return (
    <section id="foundations" className="ds-section">
      <SectionHeader
        index="01"
        title="Foundations"
        desc="Every token the system is built from — color, type, spacing, and motion. A warm-neutral canvas that carries ~90% of any screen; color is reserved for small, deliberate windows."
      />

      {/* ---- Colors ---- */}
      <div style={{ marginBottom: 'var(--space-16)' }}>
        <SubLabel>Base neutrals — ink dark to paper light</SubLabel>
        <div className="ds-grid" style={{ gridTemplateColumns: `repeat(${NEUTRALS.length}, 1fr)`, gap: '6px', marginBottom: 'var(--space-10)' }}>
          {NEUTRALS.map(([name, hex]) => (
            <div key={name} style={{ textAlign: 'center' }}>
              <div className="ds-swatch" style={{ height: 64, background: `var(${name})`, border: '1px solid var(--border-subtle)' }} />
              <span style={{ display: 'block', marginTop: 6, fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-tertiary)' }}>{hex}</span>
            </div>
          ))}
        </div>

        <SubLabel>{theme === 'jaycee' ? 'Accents — hot pink and light purple, Jaycee mode' : 'Farm accents — pulled from the mood reference'}</SubLabel>
        <div className="ds-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(150px, 1fr))', marginBottom: 'var(--space-10)' }}>
          {ACCENTS.map((a) => (
            <div key={a.name} className="ds-swatch" style={{ overflow: 'hidden' }}>
              <div style={{ height: 88, background: `var(${a.var})`, display: 'flex', alignItems: 'flex-end', padding: '10px 12px' }}>
                <div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.04em', color: a.name === 'Blossom' || a.name === 'Gold' ? 'var(--ink-950)' : '#fff' }}>{a.name}</div>
                  <div style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: a.name === 'Blossom' || a.name === 'Gold' ? 'rgba(2,2,10,0.7)' : 'rgba(255,255,255,0.75)' }}>{a.hex}</div>
                </div>
              </div>
              {a.deep && <div style={{ height: 22, background: `var(${a.deep})` }} />}
            </div>
          ))}
        </div>

        <SubLabel>Semantic roles</SubLabel>
        <div className="ds-grid" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(130px, 1fr))' }}>
          {SEMANTIC.map((s) => (
            <div key={s.label} className="ds-swatch" style={{
              height: 76, background: s.v, color: s.text, display: 'flex', alignItems: 'flex-end',
              padding: '8px 10px', border: '1px solid var(--border-subtle)',
              fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.03em',
            }}>
              {s.label}
            </div>
          ))}
        </div>
      </div>

      {/* ---- Type ---- */}
      <div style={{ marginBottom: 'var(--space-16)' }}>
        <SubLabel>Display — Barlow Condensed, always uppercase</SubLabel>
        <div style={{ marginBottom: 'var(--space-8)' }}>
          <p style={{ fontFamily: 'var(--font-display)', textTransform: 'uppercase', fontWeight: 600, fontSize: 'clamp(40px, 7vw, 80px)', letterSpacing: 'var(--tracking-display-lg)', lineHeight: 'var(--leading-tight)' }}>
            Feel Good To Use
          </p>
        </div>

        <SubLabel>Mono — DM Mono, structural labels</SubLabel>
        <p style={{ fontFamily: 'var(--font-mono)', textTransform: 'uppercase', letterSpacing: 'var(--tracking-label)', fontSize: 14, color: 'var(--text-secondary)', marginBottom: 'var(--space-8)' }}>
          // 04 — Selected Work &nbsp;&nbsp; Status: Available &nbsp;&nbsp; 2024 — Present
        </p>

        <SubLabel>Body — Karla, calm foil to Barlow&rsquo;s energy</SubLabel>
        <p style={{ fontFamily: 'var(--font-body)', fontSize: 'var(--text-body-lg)', lineHeight: 'var(--leading-relaxed)', color: 'var(--text-secondary)', maxWidth: 620, marginBottom: 'var(--space-10)' }}>
          Currently building small tools and playing with pixels on the side. Relaxed
          line-height, no tricks — this is the copy voice for anything longer than a label.
        </p>

        <SubLabel>Type scale</SubLabel>
        <div style={{ display: 'flex', flexDirection: 'column', gap: '10px' }}>
          {TYPE_SCALE.map(([name, tok, px]) => (
            <div key={name} style={{ display: 'flex', alignItems: 'baseline', gap: '18px', borderBottom: '1px solid var(--border-subtle)', paddingBottom: 8 }}>
              <span style={{ width: 90, flexShrink: 0, fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-tertiary)', textTransform: 'uppercase' }}>{name}</span>
              <span style={{ fontFamily: 'var(--font-display)', textTransform: 'uppercase', fontSize: tok, letterSpacing: '-0.01em', color: 'var(--text-primary)', lineHeight: 1 }}>Aa</span>
              <span style={{ marginLeft: 'auto', fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-tertiary)' }}>{px}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ---- Spacing ---- */}
      <div style={{ marginBottom: 'var(--space-16)' }}>
        <SubLabel>Spacing — 4px base grid</SubLabel>
        <div style={{ display: 'flex', alignItems: 'flex-end', gap: '10px', flexWrap: 'wrap' }}>
          {SPACING.map((s) => (
            <div key={s} style={{ textAlign: 'center' }}>
              <div style={{ width: `var(--space-${s})`, height: `var(--space-${s})`, background: 'var(--accent-sky)', borderRadius: 2 }} />
              <span style={{ display: 'block', marginTop: 6, fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-tertiary)' }}>{s}</span>
            </div>
          ))}
        </div>
      </div>

      {/* ---- Effects ---- */}
      <div>
        <SubLabel>Radius — soft but composed, never toy-like</SubLabel>
        <div style={{ display: 'flex', gap: '14px', flexWrap: 'wrap', marginBottom: 'var(--space-10)' }}>
          {RADII.map(([name, tok, px]) => (
            <div key={name} style={{ textAlign: 'center' }}>
              <div style={{ width: 72, height: 72, background: 'var(--accent-clay)', borderRadius: tok }} />
              <span style={{ display: 'block', marginTop: 6, fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-tertiary)' }}>{name} · {px}</span>
            </div>
          ))}
        </div>

        <SubLabel>Shadow — low elevation, warm-tinted, never pure black</SubLabel>
        <div style={{ display: 'flex', gap: '18px', flexWrap: 'wrap', marginBottom: 'var(--space-10)' }}>
          {SHADOWS.map(([name, tok]) => (
            <div key={name} style={{ textAlign: 'center' }}>
              <div style={{ width: 100, height: 64, background: 'var(--surface-card)', border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-md)', boxShadow: tok }} />
              <span style={{ display: 'block', marginTop: 10, fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-tertiary)' }}>{name}</span>
            </div>
          ))}
        </div>

        <SubLabel>Motion — quick and understated, bounce reserved for playful moments</SubLabel>
        <div style={{ display: 'flex', gap: '32px', alignItems: 'center' }}>
          <button
            onClick={() => setBounce((v) => !v)}
            style={{ background: 'transparent', border: 'none', cursor: 'pointer', padding: 0, display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 10 }}
          >
            <div
              style={{
                width: 20, height: 20, borderRadius: '50%', background: 'var(--accent-gold)',
                transform: bounce ? 'translateX(64px)' : 'translateX(0)',
                transition: 'transform var(--duration-slow) var(--ease-bounce)',
              }}
            />
            <span style={{ width: 84, height: 2, background: 'var(--border-subtle)' }} />
            <span style={{ fontFamily: 'var(--font-mono)', fontSize: 10, color: 'var(--text-tertiary)' }}>ease-bounce · click</span>
          </button>
        </div>
      </div>
    </section>
  );
}
