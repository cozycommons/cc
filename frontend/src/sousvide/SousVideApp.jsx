import React, { useEffect, useState } from 'react';
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

function usePlan(params) {
  const [state, setState] = useState({ status: 'loading' });
  const query = new URLSearchParams(params).toString();
  useEffect(() => {
    const abort = new AbortController();
    setState((s) => ({ ...s, status: 'loading' }));
    // Sliders fire on every tick; a plan costs the API about half a second.
    const timer = setTimeout(async () => {
      try {
        const response = await fetch(`${getUrl()}/sousvide/plan?${query}`, { signal: abort.signal });
        const body = await response.json().catch(() => null);
        if (!response.ok) throw new Error(body?.detail || 'Could not plan the cook.');
        setState({ status: 'ready', data: body });
      } catch (error) {
        if (error.name !== 'AbortError') setState((s) => ({ ...s, status: 'error', message: error.message }));
      }
    }, 250);
    return () => { clearTimeout(timer); abort.abort(); };
  }, [query]);
  return state;
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

function Range({ label, value, shown, min, max, step, onChange }) {
  return (
    <label className="cc-range-field sv-field">
      <span className="cc-label">{label} <output>{shown}</output></span>
      <input className="cc-range" type="range" min={min} max={max} step={step} value={value}
        onChange={(e) => onChange(Number(e.target.value))} />
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

export default function SousVideApp() {
  const [cut, setCut] = useState(CUTS[0]);
  const [mm, setMm] = useState(CUTS[0].mm);
  const [start, setStart] = useState(5);
  const [target, setTarget] = useState(54.5);
  const [boost, setBoost] = useState(3);
  const [sear, setSear] = useState(45);
  const plan = usePlan({ thickness_mm: mm, shape: cut.shape, start_c: start, target_c: target, boost_c: boost, sear_s: sear });
  const p = plan.data;
  const pickCut = (id) => { const next = CUTS.find((c) => c.id === id); setCut(next); setMm(next.mm); };
  return (
    <div className="sv-page">
      <SiteHeader product="Sous vide" to="/sousvide" icon="🥩" onSignIn={null} />
      <main className="sv-main">
        <h1 className="cc-h1">Sous vide steak</h1>
        <section className="sv-controls" aria-label="Steak">
          <Segmented label="Cut" items={CUTS.map((c) => ({ key: c.id, name: c.name }))} value={cut.id} onChange={pickCut} />
          <Range label={cut.shape === 'cylinder' ? 'Diameter' : 'Thickness'} value={mm} min={10} max={100} step={1}
            shown={`${fmtInches(mm)} · ${mm} mm`} onChange={setMm} />
          <Segmented label="Doneness" items={DONENESS.map((d) => ({ key: d.c, name: `${d.name} ${fmtF(d.c)}` }))}
            value={target} onChange={setTarget} />
          <Segmented label="Starts from" items={STARTS.map((s) => ({ key: s.c, name: `${s.name} ${fmtF(s.c)}` }))}
            value={start} onChange={setStart} />
          <Range label="Hotter bath" value={boost} min={0} max={10} step={0.5}
            shown={`+${Math.round(deltaF(boost))}°F · ${fmtF(target + boost)}`} onChange={setBoost} />
          <Range label="Sear, each side" value={sear} min={0} max={120} step={15}
            shown={sear ? `${sear} s` : 'none'} onChange={setSear} />
        </section>
        {plan.status === 'error' && <p className="cc-notice cc-notice--error" role="alert">{plan.message}</p>}
        {!p && plan.status === 'loading' && <p className="cc-caption" aria-busy="true">Working out the heat…</p>}
        {p && (
          <div className={`sv-results${plan.status === 'loading' ? ' is-stale' : ''}`} aria-busy={plan.status === 'loading'}>
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
        )}
      </main>
    </div>
  );
}
