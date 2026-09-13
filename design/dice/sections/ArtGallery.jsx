import React from 'react';
import { SceneWindow } from '../components/decor/SceneWindow';
import { HouseIcon, RoadIcon, TreesIcon, WheatIcon, HillsIcon, SunIcon, PersonIcon, DogIcon, CreatureIcon } from '../components/decor/icons';
import { SCENERY, CHARACTERS } from '../art/manifest';

const ICONS = {
  house: HouseIcon,
  road: RoadIcon,
  trees: TreesIcon,
  wheat: WheatIcon,
  hills: HillsIcon,
  sun: SunIcon,
  person: PersonIcon,
  dog: DogIcon,
  creature: CreatureIcon,
};

export function ArtGallery() {
  return (
    <section id="art" className="ds-section">
      <span className="ds-eyebrow" style={{ color: 'var(--accent-moss)' }}>// 04 — Art</span>
      <h2 style={{ margin: '14px 0 10px' }}>Art Gallery</h2>
      <p style={{ color: 'var(--text-secondary)', maxWidth: 660, fontSize: 'var(--text-body-md)', marginBottom: 'var(--space-4)' }}>
        Reserved slots for the real art: peaceful farm and nature scenery — houses,
        roads, trees — plus a small cast of star characters. Each window below is a
        placeholder built from the mood tokens; drop finished pieces into{' '}
        <code style={{ fontFamily: 'var(--font-mono)', background: 'var(--surface-sunken)', padding: '2px 6px', borderRadius: 4, fontSize: 13 }}>
          frontend/src/design/art/
        </code>{' '}
        and point <code style={{ fontFamily: 'var(--font-mono)', background: 'var(--surface-sunken)', padding: '2px 6px', borderRadius: 4, fontSize: 13 }}>manifest.js</code> at
        them — the grid updates automatically, no layout changes needed.
      </p>
      <p style={{ color: 'var(--text-tertiary)', fontSize: 13, marginBottom: 'var(--space-10)' }}>
        Same art also works as drop-in illustration inside the showcase windows and cast cards above.
      </p>

      <div style={{ marginBottom: 'var(--space-12)' }}>
        <p className="ds-eyebrow" style={{ marginBottom: 'var(--space-4)', color: 'var(--text-tertiary)' }}>Scenery — farm &amp; nature</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(240px, 1fr))', gap: 'var(--space-6)' }}>
          {SCENERY.map((s) => (
            <SceneWindow
              key={s.key}
              icon={ICONS[s.icon]}
              mood={s.mood}
              label={s.label}
              sublabel={s.sublabel}
              aspect={s.aspect}
              src={s.src}
            />
          ))}
        </div>
      </div>

      <div>
        <p className="ds-eyebrow" style={{ marginBottom: 'var(--space-4)', color: 'var(--text-tertiary)' }}>Cast — star characters</p>
        <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 'var(--space-5)' }}>
          {CHARACTERS.map((c) => (
            <SceneWindow
              key={c.key}
              icon={ICONS[c.icon]}
              mood={c.mood}
              label={c.label}
              sublabel={c.sublabel}
              aspect={c.aspect}
              iconSize={44}
              src={c.src}
            />
          ))}
        </div>
      </div>
    </section>
  );
}
