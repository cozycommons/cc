import React, { Suspense, use, useDeferredValue, useState } from 'react';
import SiteHeader from '../components/SiteHeader.jsx';
import { getUrl } from '../api.js';
import PixelKitchen from './PixelKitchen.jsx';
import '../../../design/cozy-wabi/components.css';
import './sousvide.css';

// Cut sets the shape the model heats and a typical thickness; the physics is the
// same beef either way (see docs/cozy-sous-vide.md).
export const CUTS = [
  { id: 'ribeye', name: 'Ribeye', shape: 'slab', mm: 38 },
  { id: 'strip', name: 'Strip', shape: 'slab', mm: 32 },
  { id: 'filet', name: 'Filet', shape: 'slab', mm: 50 },
  { id: 'roast', name: 'Tenderloin roast', shape: 'cylinder', mm: 75 },
];
export const DONENESS = [
  { name: 'Rare', c: 52 },
  { name: 'Medium rare', c: 54.5 },
  { name: 'Medium', c: 60 },
  { name: 'Medium well', c: 65 },
];
const STARTS = [{ name: 'Fridge', c: 5 }, { name: 'Counter', c: 20 }];
export const STRATEGIES = [
  { id: 'classic', name: 'Classic', how: 'Bath at target until the core is within 1°F of it.' },
  { id: 'hot_and_pull', name: 'Hot, then pull', how: 'Hotter bath. Pull early and let the sear finish the core.' },
  { id: 'hot_then_drop', name: 'Hot, then drop', how: 'Hotter bath, then cool it to target. Holds as long as you like.' },
];

export const toF = (c) => c * 9 / 5 + 32;
export const deltaF = (c) => c * 9 / 5;
export const fmtF = (c) => `${Math.round(toF(c))}°F`;
export const fmtInches = (mm) => `${(mm / 25.4).toFixed(2).replace(/0$/, '')}″`;
export function fmtMinutes(min) {
  const m = Math.round(min);
  if (m < 60) return `${m} min`;
  return `${Math.floor(m / 60)} h ${String(m % 60).padStart(2, '0')}`;
}

// Peak temperature to meat colour: raw, rare, medium rare, medium, well, crust.
const SHADES = [[40, [122, 28, 48]], [52, [168, 38, 58]], [55, [196, 72, 82]], [60, [214, 133, 128]],
  [65, [196, 160, 146]], [72, [160, 138, 120]], [100, [128, 96, 72]], [130, [84, 52, 34]]];
export function shade(c) {
  if (c <= SHADES[0][0]) return `rgb(${SHADES[0][1]})`;
  for (let i = 1; i < SHADES.length; i += 1) {
    const [hi, b] = SHADES[i];
    const [lo, a] = SHADES[i - 1];
    if (c <= hi) {
      const t = (c - lo) / (hi - lo);
      return `rgb(${a.map((v, k) => Math.round(v + (b[k] - v) * t)).join(',')})`;
    }
  }
  return `rgb(${SHADES.at(-1)[1]})`;
}

// One request per distinct plan, shared by every render that asks for it.
// A failed plan stays cached, so the error boundary sees it instead of
// render retrying forever; it is forgotten once a different plan is asked
// for, so coming back to it tries again. The oldest plans fall out once the
// cache holds PLAN_CACHE of them.
const PLAN_CACHE = 64;
const plans = new Map();
const failed = new Set();
export function forgetPlans() { plans.clear(); failed.clear(); }
export function planFor(query) {
  for (const q of failed) {
    if (q !== query) { plans.delete(q); failed.delete(q); }
  }
  let promise = plans.get(query);
  if (!promise) {
    promise = fetch(`${getUrl()}/sousvide/plan?${query}`).then(async (response) => {
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(body?.detail || 'Could not plan the cook.');
      return body;
    });
    promise.catch(() => failed.add(query));
    plans.set(query, promise);
    if (plans.size > PLAN_CACHE) plans.delete(plans.keys().next().value);
  }
  return promise;
}

// Shows a failed plan, and clears it when the steak changes so the next plan
// can load. (Remounting it with a key would also remount the Suspense boundary
// below, which drops the dimmed previous plan for a blank fallback.)
class PlanError extends React.Component {
  state = { error: null, query: this.props.query };
  static getDerivedStateFromError(error) { return { error }; }
  static getDerivedStateFromProps({ query }, state) {
    return query === state.query ? null : { error: null, query };
  }
  render() {
    return this.state.error
      ? <p className="cc-notice cc-notice--error" role="alert">{this.state.error.message}</p>
      : this.props.children;
  }
}

function Segmented({ label, items, value, onChange }) {
  return (
    <div className="sv-field">
      <span className="cc-label">{label}</span>
      <div className="cc-segmented sv-seg" role="radiogroup" aria-label={label}>
        {items.map((item) => (
          <button key={item.key} type="button" role="radio" className="cc-segmented__item"
            aria-checked={item.key === value} onClick={() => onChange(item.key)}>{item.name}</button>
        ))}
      </div>
    </div>
  );
}

// The label follows the thumb while it moves; the plan is only asked for once
// the thumb is let go (pointer, touch or key), since each plan costs the API
// about half a second.
function Range({ label, value, shown, min, max, step, onChange }) {
  const [draft, setDraft] = useState(null);
  const commit = () => {
    if (draft != null) onChange(draft);
    setDraft(null);
  };
  return (
    <label className="cc-range-field sv-field">
      <span className="cc-label">{label} <output>{shown(draft ?? value)}</output></span>
      <input className="cc-range" type="range" aria-label={label} min={min} max={max} step={step} value={draft ?? value}
        onChange={(e) => setDraft(Number(e.target.value))}
        onPointerUp={commit} onKeyUp={commit} onTouchEnd={commit} onBlur={commit} />
    </label>
  );
}

function Card({ strategy, row, target }) {
  const saved = row.saved_minutes;
  return (
    <article className="sv-card" data-strategy={strategy.id} aria-label={strategy.name}>
      <h2 className="cc-h3">{strategy.name}</h2>
      <p className="sv-card__time"><b>{fmtMinutes(row.minutes)}</b> in the bath</p>
      <dl className="sv-card__facts">
        <div><dt>Bath</dt><dd>{fmtF(row.bath_c)}{row.switch_minutes != null && <>, {fmtF(target)} after {fmtMinutes(row.switch_minutes)}</>}</dd></div>
        {strategy.id !== 'classic' && <div><dt>Saves</dt><dd>{saved > 0 ? fmtMinutes(saved) : 'nothing'}</dd></div>}
        <div><dt>Core peaks</dt><dd>{fmtF(row.core_peak_c)}</dd></div>
        <div><dt>Past target</dt><dd>{row.overcooked_mm} mm a side{strategy.id !== 'classic' && row.extra_overcooked_mm !== 0 ? ` (${row.extra_overcooked_mm > 0 ? '+' : ''}${row.extra_overcooked_mm})` : ''}</dd></div>
        <div><dt>Gray band</dt><dd>{row.gray_mm} mm</dd></div>
      </dl>
      <p className="cc-caption">{strategy.how}</p>
    </article>
  );
}

function CoreChart({ trace, target }) {
  const W = 360, H = 200, PAD = { top: 10, right: 8, bottom: 24, left: 34 };
  const all = STRATEGIES.flatMap((s) => trace[s.id]);
  const tmax = Math.max(...all.map((p) => p.min));
  const lo = Math.min(...all.map((p) => toF(p.core)));
  const hi = Math.max(toF(target) + 4, ...all.map((p) => toF(p.core)));
  const x = (m) => PAD.left + (m / tmax) * (W - PAD.left - PAD.right);
  const y = (f) => H - PAD.bottom - ((f - lo) / (hi - lo)) * (H - PAD.top - PAD.bottom);
  const ticks = [0, 0.25, 0.5, 0.75, 1].map((f) => Math.round((tmax * f) / 10) * 10);
  return (
    <figure className="sv-chart">
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Core temperature over time for each method">
        <line className="sv-target" x1={PAD.left} x2={W - PAD.right} y1={y(toF(target))} y2={y(toF(target))} />
        <text className="sv-axis" x={PAD.left - 4} y={y(toF(target)) + 4} textAnchor="end">{Math.round(toF(target))}</text>
        <text className="sv-axis" x={PAD.left - 4} y={y(lo) + 4} textAnchor="end">{Math.round(lo)}</text>
        {ticks.map((m) => <text key={m} className="sv-axis" x={x(m)} y={H - 6} textAnchor="middle">{fmtMinutes(m)}</text>)}
        {STRATEGIES.map((s) => (
          <polyline key={s.id} className={`sv-line sv-line--${s.id}`}
            points={trace[s.id].map((p) => `${x(p.min).toFixed(1)},${y(toF(p.core)).toFixed(1)}`).join(' ')} />
        ))}
      </svg>
      <figcaption className="sv-legend">
        {STRATEGIES.map((s) => <span key={s.id}><i className={`sv-swatch sv-line--${s.id}`} />{s.name}</span>)}
        <span><i className="sv-swatch sv-target" />Target</span>
      </figcaption>
    </figure>
  );
}

// A slab is cut through both faces, so the profile mirrors; a roast is cut through its centre too.
function Slice({ profile, label }) {
  const outer = profile.map((p) => p.peak_c);
  const row = [...outer, ...[...outer].reverse()];
  return (
    <div className="sv-slice">
      <span className="cc-caption">{label}</span>
      <div className="sv-slice__meat" role="img" aria-label={`${label} cross-section by peak temperature`}>
        {row.map((c, i) => <i key={i} style={{ background: shade(c) }} />)}
      </div>
    </div>
  );
}

export const queryOf = (steak) => new URLSearchParams({
  thickness_mm: steak.mm, shape: steak.cut.shape, start_c: steak.start, target_c: steak.target,
  boost_c: steak.boost, sear_s: steak.sear,
}).toString();

function Results({ steak, stale }) {
  const p = use(planFor(queryOf(steak)));
  const { target, sear, cut, mm } = steak;
  return (
    <div className={`sv-results${stale ? ' is-stale' : ''}`} aria-busy={stale}>
      {p.warnings.map((w) => <p key={w} className="cc-notice cc-notice--error" role="alert">{w}</p>)}
      <section className="sv-cards" aria-label="Methods">
        {STRATEGIES.map((s) => <Card key={s.id} strategy={s} row={p[s.id]} target={target} />)}
      </section>
      <PixelKitchen plan={p} target={target} sear={sear} cut={{ id: cut.id, mm }} />
      <section className="sv-section" aria-label="Core temperature">
        <h2 className="cc-h3">Core temperature</h2>
        <CoreChart trace={p.trace} target={target} />
      </section>
      <section className="sv-section" aria-label="Cross-section">
        <h2 className="cc-h3">Cross-section</h2>
        {STRATEGIES.map((s) => <Slice key={s.id} profile={p.profile[s.id]} label={s.name} />)}
      </section>
      <section className="sv-section" aria-label="Every boost">
        <h2 className="cc-h3">Hot, then pull at every boost</h2>
        <table className="sv-table">
          <thead><tr><th scope="col">Bath</th><th scope="col">Time</th><th scope="col">Saves</th><th scope="col">Past target</th></tr></thead>
          <tbody>
            {p.sweep.map((r) => (
              <tr key={r.bath_c} className={r.bath_c === p.hot_and_pull.bath_c ? 'is-chosen' : undefined}>
                <td>{fmtF(r.bath_c)}</td><td>{fmtMinutes(r.minutes)}</td>
                <td>{r.saved_minutes > 0 ? fmtMinutes(r.saved_minutes) : '–'}</td><td>{r.overcooked_mm} mm</td>
              </tr>
            ))}
          </tbody>
        </table>
      </section>
    </div>
  );
}

export default function SousVideApp() {
  const [steak, setSteak] = useState({ cut: CUTS[0], mm: CUTS[0].mm, start: 5, target: 54.5, boost: 3, sear: 45 });
  // The last plan stays on screen, dimmed, while the next one loads.
  const shown = useDeferredValue(steak);
  const set = (key) => (value) => setSteak((s) => ({ ...s, [key]: value }));
  const pickCut = (id) => { const cut = CUTS.find((c) => c.id === id); setSteak((s) => ({ ...s, cut, mm: cut.mm })); };
  const { cut, target } = steak;
  return (
    <div className="sv-page">
      <SiteHeader product="Sous vide" to="/sousvide" icon="🥩" onSignIn={null} />
      <main className="sv-main">
        <h1 className="cc-h1">Sous vide steak</h1>
        <section className="sv-controls" aria-label="Steak">
          <Segmented label="Cut" items={CUTS.map((c) => ({ key: c.id, name: c.name }))} value={cut.id} onChange={pickCut} />
          <Range label={cut.shape === 'cylinder' ? 'Diameter' : 'Thickness'} value={steak.mm} min={10} max={100} step={1}
            shown={(mm) => `${fmtInches(mm)} · ${mm} mm`} onChange={set('mm')} />
          <Segmented label="Doneness" items={DONENESS.map((d) => ({ key: d.c, name: `${d.name} ${fmtF(d.c)}` }))}
            value={target} onChange={set('target')} />
          <Segmented label="Starts from" items={STARTS.map((s) => ({ key: s.c, name: `${s.name} ${fmtF(s.c)}` }))}
            value={steak.start} onChange={set('start')} />
          <Range label="Hotter bath" value={steak.boost} min={0} max={10} step={0.5}
            shown={(b) => `+${Math.round(deltaF(b))}°F · ${fmtF(target + b)}`} onChange={set('boost')} />
          <Range label="Sear, each side" value={steak.sear} min={0} max={120} step={15}
            shown={(v) => (v ? `${v} s` : 'none')} onChange={set('sear')} />
        </section>
        <PlanError query={queryOf(shown)}>
          <Suspense fallback={<p className="cc-caption" aria-busy="true">Working out the heat…</p>}>
            <Results steak={shown} stale={shown !== steak} />
          </Suspense>
        </PlanError>
      </main>
    </div>
  );
}
