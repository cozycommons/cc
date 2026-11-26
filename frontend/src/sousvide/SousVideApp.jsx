import React, { Suspense, use, useDeferredValue, useId, useState } from 'react';
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
  middle: 'Halfway through the thickness, ¼ to ⅜″ from the bone and halfway along it, not touching it.',
  edge: 'Halfway through the thickness, in the middle of the whole steak, bone included.',
  cylinder: 'In the center of the roast, halfway along it.',
  none: 'Halfway through the thickness, in the middle of the steak.',
};
const CALIBRATION_KEY = 'sousvide.calibration';
const DEFAULT_ALPHA = 1.2; // model.Physics.diffusivity, in 1e-7 m²/s
const MM_PER_IN = 25.4;
const G_PER_LB = 453.592;
// model.DANGER_C and DANGER_HOURS: below this bath, a cook has a time limit.
const SAFE_HOLD_C = 54.4;
const SAFE_HOURS = 4;
export const STRATEGIES = [
  { id: 'classic', name: 'Classic' },
  { id: 'hot_and_pull', name: 'Hot, then pull' },
  { id: 'hot_then_drop', name: 'Hot, then cool' },
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

const EIGHTHS = { 2: '⅛', 4: '¼', 6: '⅜', 8: '½', 10: '⅝', 12: '¾', 14: '⅞' };
// A depth to the nearest sixteenth of an inch, the way a cook reads a ruler.
export function fmtDepth(mm) {
  const n = Math.round((mm / MM_PER_IN) * 16);
  if (n <= 0) return 'none';
  const whole = Math.floor(n / 16);
  const rest = n % 16;
  const part = rest ? EIGHTHS[rest] ?? `${rest}/16` : '';
  return `${whole || ''}${whole && part ? ' ' : ''}${part}″`;
}

// The method to lead with: pulling from a hotter bath, unless it saves too
// little or overcooks more than the classic cook. Hot, then cool is always
// slower than pulling; it is the choice when the steak has to wait.
export function recommended(plan) {
  const pull = plan.hot_and_pull;
  return pull.saved_minutes >= 10 && pull.extra_overcooked_mm <= 1 ? 'hot_and_pull' : 'classic';
}

// Minutes from the end of the sear until the center stops rising.
export function restMinutes(trace, searS) {
  const bathEnd = trace.filter((p) => p.phase === 'bath').at(-1).min;
  const finish = trace.filter((p) => p.phase === 'finish');
  if (!finish.length) return 0;
  const peak = finish.reduce((a, b) => (b.core > a.core ? b : a));
  return Math.max(0, peak.min - bathEnd - searS / 60);
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
    if (!this.state.error) return this.props.children;
    // The answer shows the error; the details below it just step aside.
    return this.props.quiet ? null : <p className="cc-notice cc-notice--error" role="alert">{this.state.error.message}</p>;
  }
}

// Native radios drawn as cozy-wabi segments, so arrow keys move the choice.
// An item may carry its own accessible `label` when its content is more than text.
export function Segmented({ label, items, value, onChange, showLabel = true, className = 'sv-seg' }) {
  const name = useId();
  return (
    <div className="sv-field">
      {showLabel && <span className="cc-label" aria-hidden="true">{label}</span>}
      <div className={`cc-segmented ${className}`} role="radiogroup" aria-label={label}>
        {items.map((item) => (
          <label key={item.key} className="cc-segmented__item">
            <input type="radio" className="sv-radio" name={name} value={item.key} checked={item.key === value}
              aria-label={item.label} onChange={() => onChange(item.key)} />
            {item.name}
          </label>
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

// One method as steps a cook follows, in the order they happen.
function steps(id, row, form, plan) {
  const { target, sear } = form;
  const canWait = target >= SAFE_HOLD_C; // below this, the bath is not a safe place to hold
  const pullAt = fmtF(row.pull_core_c);
  const about = `about ${fmtMinutes(row.minutes)} in`;
  const probe = PROBE[form.cut.shape === 'cylinder' ? 'cylinder' : plan.steak.bone];
  // The cook aims within READY_WITHIN_C of the target, so a center that close reads as the target.
  const endsC = Math.abs(row.core_peak_c - target) <= 0.55 ? target : row.core_peak_c;
  const rest = Math.max(1, Math.round(restMinutes(plan.trace[id], sear)));
  const out = [
    { key: 'bath', label: 'Set the bath to', value: fmtF(row.bath_c) },
    { key: 'probe', label: 'Thermometer tip', note: probe },
  ];
  if (id === 'hot_then_drop' && row.switch_minutes < row.minutes - 1) {
    out.push({ key: 'cool', label: 'Cool the bath to', value: fmtF(target), note: `at ${fmtMinutes(row.switch_minutes)}. Ice works.` });
  }
  if (id === 'hot_then_drop' && row.switch_minutes >= row.minutes - 1 && canWait) {
    out.push({ key: 'cool', label: 'Cool the bath to', value: fmtF(target),
      note: `when it reads ${pullAt}, ${about}. Ice works. It can then wait in the bath.` });
  } else {
    out.push({ key: 'out', label: 'Take it out at', value: pullAt,
      note: `on the thermometer, ${about}${id === 'hot_and_pull' ? '. Sear it right away.' : canWait ? ', or any time after.' : '.'}` });
  }
  // What a longer sear changes: the layer under the crust that goes past the target.
  const under = row.overcooked_mm > 0 ? `${fmtDepth(row.overcooked_mm)} a side cooks past ${doneness(target)}` : `nothing cooks past ${doneness(target)}`;
  out.push(sear
    ? { key: 'sear', label: 'Sear', value: `${sear} s a side`, note: `then rest ${rest} min. The center ends about ${fmtF(endsC)}, ${doneness(endsC)}.`,
      more: `Under the crust, ${under}. A longer sear browns more and cooks that layer deeper.` }
    : { key: 'sear', label: 'Rest', value: `${rest} min`, note: `The center ends about ${fmtF(endsC)}, ${doneness(endsC)}.` });
  return out;
}

function tradeoff(id, row, target) {
  const canWait = target >= SAFE_HOLD_C;
  const saved = row.saved_minutes >= 1 ? `${fmtMinutes(row.saved_minutes)} faster than classic` : 'No faster than classic';
  if (id === 'hot_and_pull') return `Fastest: ${saved}. It can’t wait: take it out on time and sear straight away.`;
  if (id === 'hot_then_drop') {
    return canWait ? `${saved}, slower than pulling, but it can wait once the bath is cool.` : `${saved}, slower than pulling.`;
  }
  return canWait ? 'The slowest and the easiest: it can wait in the bath once it’s done.' : 'The slowest and the easiest.';
}

// Food safety follows the coolest the bath gets: at or above SAFE_HOLD_C it can
// run as long as it likes, below it the whole cook stays under SAFE_HOURS.
function safety(id, row, target) {
  const coolest = id === 'hot_and_pull' ? row.bath_c : target;
  if (coolest >= SAFE_HOLD_C) return { ok: true, text: `Food safe at any length: the bath stays at ${fmtF(SAFE_HOLD_C)} or hotter.` };
  return {
    ok: row.minutes <= SAFE_HOURS * 60,
    text: `Below ${fmtF(SAFE_HOLD_C)}, keep the whole cook under ${SAFE_HOURS} h. This one takes ${fmtMinutes(row.minutes)}.`,
  };
}

function Answer({ form, stale }) {
  const p = use(planFor(queryOf(form)));
  const best = recommended(p);
  const [picked, setPicked] = useState(null);
  const id = picked ?? best;
  const row = p[id];
  const strategy = STRATEGIES.find((s) => s.id === id);
  const safe = safety(id, row, form.target);
  return (
    <section className={`sv-answer${stale ? ' is-stale' : ''}`} aria-label="What to do" aria-busy={stale}>
      <Segmented label="Method" showLabel={false} className="sv-methods" value={id} onChange={setPicked}
        items={STRATEGIES.map((s) => ({
          key: s.id, label: `${s.name}, ${fmtMinutes(p[s.id].minutes)}`,
          name: <><b>{fmtMinutes(p[s.id].minutes)}</b><span>{s.name}</span></>,
        }))} />
      <header className="sv-answer__head">
        <h2 className="cc-h3">{strategy.name}</h2>
        {id === best && <span className="cc-badge cc-badge--soft">Recommended</span>}
      </header>
      <ol className="sv-steps">
        {steps(id, row, form, p).map((s) => (
          <li key={s.key} data-step={s.key}>
            <span className="cc-label">{s.label}</span>
            {s.value && <b>{s.value}</b>}
            {s.note && <span className="sv-steps__note">{s.note}</span>}
            {s.more && <span className="sv-steps__more">{s.more}</span>}
          </li>
        ))}
      </ol>
      <p className="sv-answer__trade">{tradeoff(id, row, form.target)}</p>
      {safe.ok
        ? <p className="cc-help sv-answer__safe">{safe.text}</p>
        : <p className="cc-notice cc-notice--error" role="alert">{safe.text}</p>}
    </section>
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
      <svg viewBox={`0 0 ${W} ${H}`} role="img" aria-label="Center temperature over time for each method">
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
function Slice({ profile, label, note }) {
  const outer = profile.map((p) => p.peak_c);
  const row = [...outer, ...[...outer].reverse()];
  return (
    <div className="sv-slice">
      <span className="sv-slice__label"><b>{label}</b> {note}</span>
      <div className="sv-slice__meat" role="img" aria-label={`${label} cross-section by peak temperature`}>
        {row.map((c, i) => <i key={i} style={{ background: shade(c) }} />)}
      </div>
    </div>
  );
}

// One cook's probe log, fitted to the model. The result replaces the planner's alpha (how
// fast heat spreads through the meat) and, when the log pins it, the bath's h (how fast
// the water hands heat to the bag) for this browser until it is cleared.
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
    <details className="cc-accordion sv-calibrate">
      <summary>Tune to your kitchen{calibration ? <span className="cc-badge cc-badge--soft">{faster(calibration.alpha)}</span> : null}</summary>
      <div className="cc-accordion__content sv-calibrate__body">
        <p className="cc-help">Log the thermometer every few minutes through one cook in a bath held at one temperature, with the
          steak set above as you measured it. One reading per line: minutes since it went in, then °F.</p>
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
          <div role="status">
            <p className="cc-help">
              Your steak {faster(f.alpha)} than the default. Times now miss your readings
              by {deltaF(f.rms_c).toFixed(1)}°F, against {deltaF(f.default_rms_c).toFixed(1)}°F before.
              {f.h_identifiable === false && ' The log couldn’t tell how fast your bath heats, so that stays at the default.'}
              {f.alpha_on_bound && ' The fit hit its limit: check the thickness, the starting temperature and where the thermometer sat.'}
            </p>
            <p className="cc-caption">Diffusivity α {f.alpha} ×10⁻⁷ m²/s (default {DEFAULT_ALPHA}){f.h_fitted ? `, bath h ${f.h_bath} W/m²·K` : ''}</p>
          </div>
        )}
      </div>
    </details>
  );
}

// A fitted diffusivity against the default, as a cook would say it.
function faster(alpha) {
  const pct = Math.round((alpha / DEFAULT_ALPHA - 1) * 100);
  return pct === 0 ? 'heats as expected' : `heats ${Math.abs(pct)}% ${pct > 0 ? 'faster' : 'slower'}`;
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

// Everything behind the answer: how each method heats the steak, what it leaves
// inside, every hotter bath, and how the steak was sized.
function Details({ form, stale }) {
  const p = use(planFor(queryOf(form)));
  const { target, sear, cut, mm } = form;
  const slab = cut.shape === 'slab';
  const sized = p.steak;
  const done = doneness(target);
  return (
    <div className={`sv-details${stale ? ' is-stale' : ''}`} aria-busy={stale}>
      <section className="sv-section" aria-label="Center temperature">
        <h2 className="cc-h3">Center temperature</h2>
        <CoreChart trace={p.trace} target={target} />
      </section>
      <section className="sv-section" aria-label="Cross-section">
        <h2 className="cc-h3">Cut open</h2>
        {STRATEGIES.map((s) => {
          const [lo, hi] = p[s.id].core_peak_range_c.map((c) => Math.round(toF(c)));
          return (
            <Slice key={s.id} profile={p.profile[s.id]} label={s.name}
              note={`center ${lo === hi ? `${lo}°F` : `${lo} to ${hi}°F`}, ${fmtDepth(p[s.id].overcooked_mm)} past ${done} under each side`} />
          );
        })}
        <p className="cc-help">The center’s range is a pan half or twice as hot as assumed.</p>
      </section>
      <PixelKitchen plan={p} target={target} sear={sear} cut={{ id: cut.id, mm, bone: slab ? sized.bone : 'none' }} />
      <details className="cc-accordion">
        <summary>Every hot bath</summary>
        <div className="cc-accordion__content">
          <p className="cc-help">Hot, then pull at each bath temperature. A hotter bath is faster; past a point it overcooks the outside before the sear does. Depths are meat past {done}.</p>
          <table className="sv-table">
            <thead><tr><th scope="col">Bath</th><th scope="col">Time</th><th scope="col">Saves</th><th scope="col">Overcooked, before sear</th><th scope="col">after sear</th></tr></thead>
            <tbody>
              {p.sweep.map((r) => (
                <tr key={r.bath_c} className={r.bath_c === p.hot_and_pull.bath_c ? 'is-chosen' : undefined}>
                  <td>{fmtF(r.bath_c)}</td><td>{fmtMinutes(r.minutes)}</td>
                  <td>{r.saved_minutes >= 1 ? fmtMinutes(r.saved_minutes) : '–'}</td>
                  <td>{r.bath_overcooked_mm > 0 ? `${fmtDepth(r.bath_overcooked_mm)} a side` : '–'}</td>
                  <td>{r.overcooked_mm > 0 ? `${fmtDepth(r.overcooked_mm)} a side` : '–'}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </details>
      <details className="cc-accordion">
        <summary>How the steak was sized</summary>
        <div className="cc-accordion__content">
          <p className="cc-help">
            {sized.sized_by === 'weight' && `Width and length from the weight: ${
              [sized.width_mm && `${fmtInches(sized.width_mm)}${slab ? '' : ' across'}`, sized.length_mm && `${fmtInches(sized.length_mm)}${slab ? '' : ' long'}`]
                .filter(Boolean).join(' × ')}. `}
            {sized.sized_by === 'measured' && 'Width and length as measured. '}
            {sized.sized_by === 'thickness' && 'No weight or width, so this treats the steak as endlessly wide: it runs long unless the steak is five times wider than thick. '}
            {p.thickness_only_minutes - p.classic.minutes > 1
              && `Thickness alone would say ${fmtMinutes(p.thickness_only_minutes)} for the classic cook. `}
            {slab && sized.bone === 'middle' && 'The thermometer spot next to the bone is the last to cook; the middle of the meat reads about 2°F higher.'}
          </p>
        </div>
      </details>
    </div>
  );
}

const formFor = (cut, rest) => ({
  ...rest, cut, mm: cut.mm, bone: cut.bone, lb: String(cut.lb), widthIn: '', lengthIn: '',
});

const startNote = (c) => (c <= 7 ? ' · fridge' : c >= 18 ? ' · room temp' : '');

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
  const lb = measured(form.lb);
  const query = queryOf(shown);
  const loading = <p className="cc-caption" aria-busy="true">Working out the heat…</p>;
  return (
    <div className="sv-page">
      <SiteHeader product="Sous vide" to="/sousvide" icon="🥩" onSignIn={null} />
      <main className="sv-main">
        <div className="sv-top">
          <div className="sv-lead">
            <h1 className="cc-h1">Sous vide steak</h1>
            <p className="sv-steak-line">
              {cut.name}, {fmtInches(form.mm)}{lb ? `, ${lb} lb` : ''}, {fmtF(form.start)} to {fmtF(target)} {doneness(target)}
              {' '}<a className="cc-inline-link" href="#steak">Change</a>
            </p>
            <PlanError query={query}>
              <Suspense fallback={loading}>
                <Answer form={shown} stale={shown !== form} />
              </Suspense>
            </PlanError>
          </div>
          <section className="sv-controls" id="steak" aria-label="Steak">
            <h2 className="sv-controls__title">Your steak</h2>
            <label className="cc-field sv-field">
              <span className="cc-label">Cut</span>
              <select className="cc-select" value={cut.id} onChange={(e) => pickCut(e.target.value)}>
                {CUTS.map((c) => <option key={c.id} value={c.id}>{c.name}</option>)}
              </select>
            </label>
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
            <Range label="Starts at" value={form.start} min={0} max={30} step={0.5}
              shown={(c) => `${fmtF(c)}${startNote(c)}`} onChange={set('start')} />
            <h2 className="sv-controls__title">Your cook</h2>
            <Range label="Doneness" value={target} min={49} max={68} step={0.5}
              shown={(c) => `${fmtF(c)} · ${doneness(c)}`} onChange={set('target')} />
            <Range label="Hot bath, for the faster methods" value={form.boost} min={0} max={10} step={0.5}
              shown={(b) => `${fmtF(target + b)} · +${Math.round(toF(target + b)) - Math.round(toF(target))}°F`} onChange={set('boost')} />
            <Range label="Sear, each side" value={form.sear} min={0} max={120} step={15}
              shown={(v) => (v ? `${v} s` : 'none')} onChange={set('sear')} />
          </section>
        </div>
        <PlanError query={query} quiet>
          <Suspense fallback={null}>
            <Details form={shown} stale={shown !== form} />
          </Suspense>
        </PlanError>
        <Calibrate steak={steakParams(form)} calibration={form.calibration} onChange={calibrate} />
      </main>
    </div>
  );
}
