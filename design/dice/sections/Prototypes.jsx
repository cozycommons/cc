import React from 'react';
import { Card } from '../components/core/Card';
import { Badge } from '../components/core/Badge';
import { Button } from '../components/core/Button';
import { IconButton } from '../components/core/IconButton';
import { Input } from '../components/forms/Input';
import { Select } from '../components/forms/Select';
import { Switch } from '../components/forms/Switch';
import { Checkbox } from '../components/forms/Checkbox';
import { SceneWindow } from '../components/decor/SceneWindow';
import { HouseIcon, RoadIcon, TreesIcon, PersonIcon, DogIcon, CreatureIcon } from '../components/decor/icons';

function ProtoLabel({ children, sub }) {
  return (
    <div style={{ marginBottom: 'var(--space-5)' }}>
      <p className="ds-eyebrow" style={{ color: 'var(--accent-blossom-deep, var(--accent-blossom))' }}>{children}</p>
      {sub && <p style={{ fontSize: 13, color: 'var(--text-tertiary)', marginTop: 4 }}>{sub}</p>}
    </div>
  );
}

/* ---- 1. Product navbar, framed like a small browser window ---- */
function NavbarPrototype() {
  return (
    <div style={{ border: '1px solid var(--border-subtle)', borderRadius: 'var(--radius-xl)', overflow: 'hidden', boxShadow: 'var(--shadow-md)' }}>
      <div style={{ display: 'flex', gap: 6, padding: '10px 14px', background: 'var(--surface-sunken)', borderBottom: '1px solid var(--border-subtle)' }}>
        {['var(--accent-berry)', 'var(--accent-gold)', 'var(--accent-moss)'].map((c) => (
          <span key={c} style={{ width: 10, height: 10, borderRadius: '50%', background: c, opacity: 0.75 }} />
        ))}
      </div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', gap: 16, padding: '14px 20px', background: 'var(--surface-card)', flexWrap: 'wrap' }}>
        <div style={{ display: 'flex', alignItems: 'center', gap: 22, flexWrap: 'wrap' }}>
          <span style={{ display: 'flex', alignItems: 'center', gap: 8, fontFamily: 'var(--font-display)', textTransform: 'uppercase', fontSize: 18, letterSpacing: 'var(--tracking-display-xs)' }}>
            <span style={{ width: 22, height: 22, borderRadius: 6, background: 'var(--accent-moss)', display: 'inline-block' }} />
            Lantern
          </span>
          <div style={{ display: 'flex', gap: 18 }}>
            {['Overview', 'Fields', 'Orders', 'Reports'].map((l, i) => (
              <span key={l} style={{ fontFamily: 'var(--font-mono)', fontSize: 12, textTransform: 'uppercase', letterSpacing: 'var(--tracking-label)', color: i === 0 ? 'var(--text-primary)' : 'var(--text-tertiary)', borderBottom: i === 0 ? '2px solid var(--accent-moss)' : '2px solid transparent', paddingBottom: 4 }}>
                {l}
              </span>
            ))}
          </div>
        </div>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
          <div style={{ display: 'none' }} />
          <div style={{ width: 160, maxWidth: '40vw' }}>
            <input
              placeholder="Search…"
              style={{
                width: '100%', fontFamily: 'var(--font-body)', fontSize: 13, padding: '8px 12px',
                borderRadius: 'var(--radius-pill)', border: '1.5px solid var(--border-default)', background: 'var(--surface-sunken)', outline: 'none',
              }}
            />
          </div>
          <IconButton label="Notifications" size="sm">
            <svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round"><path d="M18 8a6 6 0 10-12 0c0 7-3 9-3 9h18s-3-2-3-9" /><path d="M13.7 21a2 2 0 01-3.4 0" /></svg>
          </IconButton>
          <span style={{ width: 32, height: 32, borderRadius: '50%', background: 'linear-gradient(160deg, var(--accent-gold), var(--accent-clay-deep))', display: 'inline-block', boxShadow: 'var(--shadow-xs)' }} />
        </div>
      </div>
    </div>
  );
}

/* ---- 2. Featured showcase windows ---- */
const FEATURED = [
  { title: 'Fieldnotes', tag: 'Design', badge: 'moss', desc: 'A minimal journaling app with a cozy, seasonal palette.', icon: HouseIcon, mood: 'dusk' },
  { title: 'Wayfinder', tag: 'Design', badge: 'sky', desc: 'Wayfinding system for a small regional trail network.', icon: RoadIcon, mood: 'sky' },
  { title: 'Pocket Garden', tag: 'Code', badge: 'blossom', desc: 'Tiny plant-care tracker, built as a weekend project.', icon: TreesIcon, mood: 'blossom' },
];

function ShowcaseWindows() {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(260px, 1fr))', gap: 'var(--space-6)' }}>
      {FEATURED.map((p, i) => (
        <Card key={p.title} accent={i === 0} padded={false} style={{ overflow: 'hidden' }}>
          <SceneWindow icon={p.icon} mood={p.mood} aspect="16 / 10" style={{ borderRadius: 0, border: 'none' }} />
          <div style={{ padding: 'var(--space-5)' }}>
            <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'flex-start', marginBottom: 8 }}>
              <h4 style={{ fontSize: 20 }}>{p.title}</h4>
              <Badge color={p.badge}>{p.tag}</Badge>
            </div>
            <p style={{ fontSize: 14, color: 'var(--text-secondary)' }}>{p.desc}</p>
          </div>
        </Card>
      ))}
    </div>
  );
}

/* ---- 3. Farm-stats dashboard widget ---- */
const STATS = [
  { label: 'Crops harvested', value: '128', pct: 78, color: 'var(--accent-moss)' },
  { label: 'Gold earned', value: '2,450g', pct: 54, color: 'var(--accent-gold)' },
  { label: 'Energy', value: '78%', pct: 78, color: 'var(--accent-sky)' },
  { label: 'Friendship: Robin', pct: 92, value: '92%', color: 'var(--accent-blossom-deep)' },
];

function DashboardWidget() {
  return (
    <Card>
      <div style={{ display: 'flex', justifyContent: 'space-between', alignItems: 'baseline', marginBottom: 'var(--space-6)' }}>
        <div>
          <p className="ds-eyebrow" style={{ color: 'var(--accent-moss)' }}>// Today&rsquo;s Yield</p>
          <h4 style={{ fontSize: 24, marginTop: 6 }}>Farm Overview</h4>
        </div>
        <Badge color="gold">Day 14 — Spring</Badge>
      </div>
      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(180px, 1fr))', gap: 'var(--space-5)' }}>
        {STATS.map((s) => (
          <div key={s.label}>
            <div style={{ display: 'flex', justifyContent: 'space-between', marginBottom: 6 }}>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, textTransform: 'uppercase', letterSpacing: '0.04em', color: 'var(--text-tertiary)' }}>{s.label}</span>
              <span style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-primary)' }}>{s.value}</span>
            </div>
            <div style={{ height: 6, borderRadius: 'var(--radius-pill)', background: 'var(--surface-sunken)', overflow: 'hidden' }}>
              <div style={{ width: `${s.pct}%`, height: '100%', background: s.color, borderRadius: 'var(--radius-pill)' }} />
            </div>
          </div>
        ))}
      </div>
    </Card>
  );
}

/* ---- 4. Cast / character cards (ties into the art gallery) ---- */
const CAST = [
  { name: 'The Farmer', role: 'Player character', icon: PersonIcon, mood: 'meadow', badge: 'moss' },
  { name: 'Biscuit', role: 'Dog companion', icon: DogIcon, mood: 'dusk', badge: 'clay' },
  { name: 'Nib', role: 'Pixel creature', icon: CreatureIcon, mood: 'sky', badge: 'sky' },
];

function CastCards() {
  return (
    <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(160px, 1fr))', gap: 'var(--space-5)' }}>
      {CAST.map((c) => (
        <Card key={c.name} padded={false} style={{ overflow: 'hidden' }}>
          <SceneWindow icon={c.icon} mood={c.mood} aspect="1 / 1" iconSize={44} style={{ borderRadius: 0, border: 'none' }} />
          <div style={{ padding: 'var(--space-4)' }}>
            <p style={{ fontFamily: 'var(--font-display)', textTransform: 'uppercase', fontSize: 17, letterSpacing: 'var(--tracking-display-xs)' }}>{c.name}</p>
            <div style={{ marginTop: 6 }}><Badge color={c.badge}>{c.role}</Badge></div>
          </div>
        </Card>
      ))}
    </div>
  );
}

/* ---- 5. Settings form ---- */
function SettingsForm() {
  const [notify, setNotify] = React.useState(true);
  const [newsletter, setNewsletter] = React.useState(false);
  return (
    <Card style={{ maxWidth: 460 }}>
      <p className="ds-eyebrow" style={{ color: 'var(--accent-sky)', marginBottom: 4 }}>// Account</p>
      <h4 style={{ fontSize: 22, marginBottom: 'var(--space-6)' }}>Settings</h4>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 16 }}>
        <Input label="Display name" placeholder="Jason Keung" />
        <Input label="Email" type="email" placeholder="you@example.com" />
        <Select
          label="Timezone"
          value="et"
          onChange={() => {}}
          options={[
            { value: 'et', label: 'Eastern (ET)' },
            { value: 'pt', label: 'Pacific (PT)' },
            { value: 'utc', label: 'UTC' },
          ]}
        />
        <Switch label="Email notifications" checked={notify} onChange={setNotify} />
        <Checkbox label="Send me the occasional newsletter" checked={newsletter} onChange={setNewsletter} />
        <div style={{ display: 'flex', gap: 10, marginTop: 6 }}>
          <Button variant="accent">Save changes</Button>
          <Button variant="ghost">Cancel</Button>
        </div>
      </div>
    </Card>
  );
}

export function Prototypes() {
  return (
    <section id="prototypes" className="ds-section">
      <span className="ds-eyebrow" style={{ color: 'var(--accent-clay)' }}>// 03 — Prototypes</span>
      <h2 style={{ margin: '14px 0 10px' }}>Composed, Not Reinvented</h2>
      <p style={{ color: 'var(--text-secondary)', maxWidth: 640, fontSize: 'var(--text-body-md)', marginBottom: 'var(--space-12)' }}>
        The patterns that show up over and over across real products — a nav bar, a
        featured-work grid, a stats widget, a settings form — built from nothing but
        the primitives above.
      </p>

      <div style={{ marginBottom: 'var(--space-14)' }}>
        <ProtoLabel sub="Sticky, framed, composed from Button / IconButton / Tag patterns.">Navigation bar</ProtoLabel>
        <NavbarPrototype />
      </div>

      <div style={{ marginBottom: 'var(--space-14)' }}>
        <ProtoLabel sub="Card + Badge + a scenery window — the pattern behind the homepage's featured project tiles.">Featured showcase windows</ProtoLabel>
        <ShowcaseWindows />
      </div>

      <div style={{ display: 'grid', gridTemplateColumns: 'repeat(auto-fit, minmax(320px, 1fr))', gap: 'var(--space-10)', marginBottom: 'var(--space-14)', alignItems: 'start' }}>
        <div>
          <ProtoLabel sub="Card + mono labels + slim progress bars.">Dashboard widget</ProtoLabel>
          <DashboardWidget />
        </div>
        <div>
          <ProtoLabel sub="Reserves space for the real character art below.">Cast / character cards</ProtoLabel>
          <CastCards />
        </div>
      </div>

      <div>
        <ProtoLabel sub="Input + Select + Switch + Checkbox assembled into a real form.">Settings panel</ProtoLabel>
        <SettingsForm />
      </div>
    </section>
  );
}
