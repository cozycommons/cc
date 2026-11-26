import React, { Suspense, use, useDeferredValue, useState } from 'react';
import SiteHeader from '../components/SiteHeader.jsx';
import { getUrl } from '../api.js';
import PixelKitchen from './PixelKitchen.jsx';
import '../../../design/cozy-wabi/components.css';
import './sousvide.css';

// A cut is a starting point: the shape the model heats, where the bone sits and a typical
// size. The cook's own measurements replace the size; the physics is the same beef either
// way, because the cut tells the model less than a ruler does (see docs/cozy-sous-vide.md).
export const CUTS = [
  { id: 'ribeye-bone', name: 'Bone-in ribeye', shape: 'slab', mm: 51, bone: 'middle', lb: 2.94 },
  { id: 'ribeye', name: 'Ribeye', shape: 'slab', mm: 38, bone: 'none', lb: 1 },
  { id: 'strip', name: 'Strip', shape: 'slab', mm: 32, bone: 'none', lb: 0.9 },
  { id: 'filet', name: 'Filet', shape: 'puck', mm: 50, bone: 'none', lb: 0.5 },
  { id: 'roast', name: 'Tenderloin roast', shape: 'cylinder', mm: 75, bone: 'none', lb: 2.5 },
];
// Lowest target that still earns each name.
export const DONENESS = [
  { name: 'rare', c: 0 },
  { name: 'medium rare', c: 54 },
  { name: 'medium', c: 57.5 },
  { name: 'medium well', c: 63 },
  { name: 'well done', c: 68 },
];
export const doneness = (c) => DONENESS.filter((d) => c >= d.c).at(-1).name;
const BONES = [{ key: 'none', name: 'None' }, { key: 'edge', name: 'Along an edge' }, { key: 'middle', name: 'Through the middle' }];
// Where the coldest meat is, from the 2-D solves in backend/sousvide/experiments.
const PROBE = {
  middle: 'Probe tip at mid-thickness, ¼ to ⅜ in from the bone and halfway along it, not touching it. The middle of the meat reads about 2°F higher.',
  edge: 'Probe tip at mid-thickness in the middle of the whole steak, bone included.',
  cylinder: 'Probe tip on the roast’s axis, halfway along it.',
  none: 'Probe tip at mid-thickness in the middle of the steak.',
};
const CALIBRATION_KEY = 'sousvide.calibration';
const MM_PER_IN = 25.4;
const G_PER_LB = 453.592;
export const STRATEGIES = [
  { id: 'classic', name: 'Classic', how: 'Bath at target until the core is within 1°F of it.' },
  { id: 'hot_and_pull', name: 'Hot, then pull', how: 'Hotter bath. Pull early and let the sear finish the core.' },
  { id: 'hot_then_drop', name: 'Hot, then drop', how: 'Hotter bath, then cool it to target. Holds as long as you like.' },
];

export const toF = (c) => c * 9 / 5 + 32;
export const toC = (f) => (f - 32) * 5 / 9;
// A typed measurement, or null while the box is empty or mid-edit.
const measured = (text) => { const v = parseFloat(text); return Number.isFinite(v) && v > 0 ? v : null; };
export function parseLog(text) {
  return text.split('\n').map((line) => line.trim().split(/[\s,;]+/).map(Number))
    .filter((pair) => pair.length >= 2 && pair.every(Number.isFinite)).map(([min, f]) => [min, toC(f)]);
}
function savedCalibration() {
  try { return JSON.parse(localStorage.getItem(CALIBRATION_KEY)) || null; } catch { return null; }
}
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

// Like Range: typing edits a draft, and the value is committed on blur or Enter,
// so a half-typed "2." never asks the API for a plan.
function Measure({ label, value, placeholder, step, onChange }) {
  const [draft, setDraft] = useState(null);
  const commit = () => {
    if (draft != null && draft !== value) onChange(draft);
    setDraft(null);
  };
  return (
    <label className="cc-field sv-field">
      <span className="cc-label">{label}</span>
      <input className="cc-input" type="number" inputMode="decimal" min="0" step={step} value={draft ?? value}
        placeholder={placeholder} onChange={(e) => setDraft(e.target.value)} onBlur={commit}
        onKeyDown={(e) => { if (e.key === 'Enter') commit(); }} />
    </label>
  );
}

function Card({ strategy, row, target }) {
  const saved = row.saved_minutes;
  const [low, high] = row.core_peak_range_c.map((c) => Math.round(toF(c)));
  return (
    <article className="sv-card" data-strategy={strategy.id} aria-label={strategy.name}>
      <h2 className="cc-h3">{strategy.name}</h2>
      <p className="sv-card__time"><b>{fmtMinutes(row.minutes)}</b> in the bath</p>
      <dl className="sv-card__facts">
        <div><dt>Bath</dt><dd>{fmtF(row.bath_c)}{row.switch_minutes != null && <>, {fmtF(target)} after {fmtMinutes(row.switch_minutes)}</>}</dd></div>
        {strategy.id !== 'classic' && <div><dt>Saves</dt><dd>{saved > 0 ? fmtMinutes(saved) : 'nothing'}</dd></div>}
        {strategy.id === 'hot_and_pull' && <div><dt>Pull when the core reads</dt><dd>{fmtF(row.pull_core_c)}</dd></div>}
        <div><dt>Core peaks</dt><dd>{fmtF(row.core_peak_c)}{low !== high && ` (${low} to ${high} by sear)`}</dd></div>
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

// One cook's probe log, fitted to the model. The result replaces the planner's alpha (and
// the bath's h when the log pins it) for this browser until it is cleared.
function Calibrate({ steak, calibration, onChange }) {
  const [log, setLog] = useState('');
  const [bathF, setBathF] = useState('135');
  const [state, setState] = useState({ status: 'idle' });
  const readings = parseLog(log);
  const fit = async () => {
    setState({ status: 'loading' });
    try {
      const response = await fetch(`${getUrl()}/sousvide/calibrate`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...steak, bath_c: toC(Number(bathF)), readings, fit_h: true }),
      });
      const body = await response.json().catch(() => null);
      if (!response.ok) throw new Error(typeof body?.detail === 'string' ? body.detail : 'Could not fit that log.');
      setState({ status: 'ready', fit: body });
      onChange({ alpha: body.alpha, h_bath: body.h_fitted ? body.h_bath : undefined });
    } catch (error) {
      setState({ status: 'error', message: error.message });
    }
  };
  const f = state.fit;
  return (
    <details className="sv-calibrate">
      <summary className="cc-label">Calibrate from a probe log{calibration ? ` · using α ${calibration.alpha}` : ''}</summary>
      <p className="cc-help">Log the core every few minutes during one cook in a bath held at one temperature, with the steak entered above
        as measured. One reading per line: minutes since it went in, then °F.</p>
      <div className="sv-measures">
        <Measure label="Bath °F" value={bathF} step="0.5" onChange={setBathF} />
      </div>
      <label className="cc-field sv-field">
        <span className="cc-label">Readings</span>
        <textarea className="cc-textarea" rows={6} value={log} placeholder={'0, 41\n10, 48\n20, 71'} onChange={(e) => setLog(e.target.value)} />
      </label>
      <div className="cc-button-row">
        <button type="button" className="cc-button cc-button--primary" disabled={readings.length < 3 || state.status === 'loading'} onClick={fit}>
          Fit {readings.length} readings</button>
        {calibration && <button type="button" className="cc-button cc-button--ghost" onClick={() => { onChange(null); setState({ status: 'idle' }); }}>
          Back to defaults</button>}
      </div>
      {state.status === 'error' && <p className="cc-notice cc-notice--error" role="alert">{state.message}</p>}
      {f && (
        <p className="cc-caption" role="status">
          Fitted α {f.alpha} (default 1.2){f.h_fitted ? ` and bath h ${f.h_bath}` : ''}. The model now misses your readings
          by {deltaF(f.rms_c).toFixed(1)}°F, against {deltaF(f.default_rms_c).toFixed(1)}°F before.
          {f.h_identifiable === false && ' The log could not pin the bath’s h, so it stays at the default.'}
          {f.alpha_on_bound && ' The fit hit its limit: check the thickness, the start temperature and where the probe sat.'}
        </p>
      )}
    </details>
  );
}

// What the API needs about the steak itself: only what was measured, so it
// sizes the rest from the weight.
export function steakParams(form) {
  const { cut, mm, bone, lb, widthIn, lengthIn, start } = form;
  return {
    thickness_mm: mm, shape: cut.shape, start_c: start,
    ...(measured(lb) && { weight_g: Math.round(measured(lb) * G_PER_LB) }),
    ...(cut.shape !== 'cylinder' && measured(widthIn) && { width_mm: Math.round(measured(widthIn) * MM_PER_IN) }),
    ...(cut.shape !== 'puck' && measured(lengthIn) && { length_mm: Math.round(measured(lengthIn) * MM_PER_IN) }),
    ...(cut.shape === 'slab' && bone !== 'none' && { bone }),
  };
}

export const queryOf = (form) => new URLSearchParams({
  ...steakParams(form), target_c: form.target, boost_c: form.boost, sear_s: form.sear,
  ...(form.calibration?.alpha && { alpha: form.calibration.alpha }),
  ...(form.calibration?.h_bath && { h_bath: form.calibration.h_bath }),
}).toString();

function Results({ form, stale }) {
  const p = use(planFor(queryOf(form)));
  const { target, sear, cut, mm } = form;
  const slab = cut.shape === 'slab';
  const sized = p.steak;
  return (
    <div className={`sv-results${stale ? ' is-stale' : ''}`} aria-busy={stale}>
      {p.warnings.map((w) => <p key={w} className="cc-notice cc-notice--error" role="alert">{w}</p>)}
      <p className="cc-caption sv-basis">
        {sized.sized_by === 'weight' && `Sized from the weight as ${
          [sized.width_mm && `${fmtInches(sized.width_mm)}${slab ? '' : ' across'}`, sized.length_mm && `${fmtInches(sized.length_mm)}${slab ? '' : ' long'}`]
            .filter(Boolean).join(' × ')}. `}
        {sized.sized_by === 'thickness' && 'No weight or width, so this is an endless slab: it runs long unless the steak is five thicknesses wide. '}
        {p.thickness_only_minutes - p.classic.minutes > 1
          && `Thickness alone would say ${fmtMinutes(p.thickness_only_minutes)} for the classic cook. `}
        {PROBE[cut.shape === 'cylinder' ? 'cylinder' : sized.bone]}
      </p>
      <section className="sv-cards" aria-label="Methods">
        {STRATEGIES.map((s) => <Card key={s.id} strategy={s} row={p[s.id]} target={target} />)}
      </section>
      <PixelKitchen plan={p} target={target} sear={sear} cut={{ id: cut.id, mm, bone: slab ? sized.bone : 'none' }} />
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

const formFor = (cut, rest) => ({
  ...rest, cut, mm: cut.mm, bone: cut.bone, lb: String(cut.lb), widthIn: '', lengthIn: '',
});

export default function SousVideApp() {
  const [form, setForm] = useState(() => formFor(CUTS[0], {
    start: 5, target: 54.5, boost: 3, sear: 45, calibration: savedCalibration(),
  }));
  // The last plan stays on screen, dimmed, while the next one loads.
  const shown = useDeferredValue(form);
  const set = (key) => (value) => setForm((f) => ({ ...f, [key]: value }));
  const pickCut = (id) => setForm((f) => formFor(CUTS.find((c) => c.id === id), f));
  const calibrate = (next) => {
    setForm((f) => ({ ...f, calibration: next }));
    try {
      if (next) localStorage.setItem(CALIBRATION_KEY, JSON.stringify(next));
      else localStorage.removeItem(CALIBRATION_KEY);
    } catch { /* private mode: the fit still applies until the page closes */ }
  };
  const { cut, target } = form;
  const slab = cut.shape === 'slab';
  return (
    <div className="sv-page">
      <SiteHeader product="Sous vide" to="/sousvide" icon="🥩" onSignIn={null} />
      <main className="sv-main">
        <h1 className="cc-h1">Sous vide steak</h1>
        <section className="sv-controls" aria-label="Steak">
          <Segmented label="Cut" items={CUTS.map((c) => ({ key: c.id, name: c.name }))} value={cut.id} onChange={pickCut} />
          <Range label={cut.shape === 'cylinder' ? 'Diameter' : 'Thickness'} value={form.mm} min={10} max={100} step={1}
            shown={(mm) => `${fmtInches(mm)} · ${mm} mm`} onChange={set('mm')} />
          <div className="sv-measures">
            <Measure label="Weight, lb" value={form.lb} step="0.01" onChange={set('lb')} />
            {cut.shape !== 'cylinder' && <Measure label={slab ? 'Width, in' : 'Diameter, in'} value={form.widthIn} step="0.1"
              placeholder="from weight" onChange={set('widthIn')} />}
            {cut.shape !== 'puck' && <Measure label="Length, in" value={form.lengthIn} step="0.1" placeholder="from weight"
              onChange={set('lengthIn')} />}
          </div>
          {slab && <Segmented label="Bone" items={BONES} value={form.bone} onChange={set('bone')} />}
          <Range label="Target" value={target} min={49} max={68} step={0.5}
            shown={(c) => `${fmtF(c)} · ${doneness(c)}`} onChange={set('target')} />
          <Range label="Starts at" value={form.start} min={0} max={30} step={0.5} shown={fmtF} onChange={set('start')} />
          <Range label="Hotter bath" value={form.boost} min={0} max={10} step={0.5}
            shown={(b) => `+${Math.round(deltaF(b))}°F · ${fmtF(target + b)}`} onChange={set('boost')} />
          <Range label="Sear, each side" value={form.sear} min={0} max={120} step={15}
            shown={(v) => (v ? `${v} s` : 'none')} onChange={set('sear')} />
        </section>
        <Calibrate steak={steakParams(form)} calibration={form.calibration} onChange={calibrate} />
        <PlanError query={queryOf(shown)}>
          <Suspense fallback={<p className="cc-caption" aria-busy="true">Working out the heat…</p>}>
            <Results form={shown} stale={shown !== form} />
          </Suspense>
        </PlanError>
      </main>
    </div>
  );
}
