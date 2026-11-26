import React, { useEffect, useState } from 'react';
import SiteHeader from '../components/SiteHeader.jsx';
import { getUrl } from '../api.js';
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

function Measure({ label, value, placeholder, step, onChange }) {
  return (
    <label className="cc-field sv-field">
      <span className="cc-label">{label}</span>
      <input className="cc-input" type="number" inputMode="decimal" min="0" step={step} value={value}
        placeholder={placeholder} onChange={(e) => onChange(e.target.value)} />
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

export default function SousVideApp() {
  const [cut, setCut] = useState(CUTS[0]);
  const [mm, setMm] = useState(CUTS[0].mm);
  const [bone, setBone] = useState(CUTS[0].bone);
  const [lb, setLb] = useState(String(CUTS[0].lb));
  const [widthIn, setWidthIn] = useState('');
  const [lengthIn, setLengthIn] = useState('');
  const [start, setStart] = useState(5);
  const [target, setTarget] = useState(54.5);
  const [boost, setBoost] = useState(3);
  const [sear, setSear] = useState(45);
  const [calibration, setCalibration] = useState(savedCalibration);
  const slab = cut.shape === 'slab';
  // Only what was measured goes to the API; it sizes the rest from the weight.
  const steak = {
    thickness_mm: mm, shape: cut.shape, start_c: start,
    ...(measured(lb) && { weight_g: Math.round(measured(lb) * G_PER_LB) }),
    ...(cut.shape !== 'cylinder' && measured(widthIn) && { width_mm: Math.round(measured(widthIn) * MM_PER_IN) }),
    ...(cut.shape !== 'puck' && measured(lengthIn) && { length_mm: Math.round(measured(lengthIn) * MM_PER_IN) }),
    ...(slab && bone !== 'none' && { bone }),
  };
  const plan = usePlan({
    ...steak, target_c: target, boost_c: boost, sear_s: sear,
    ...(calibration?.alpha && { alpha: calibration.alpha }), ...(calibration?.h_bath && { h_bath: calibration.h_bath }),
  });
  const p = plan.data;
  const pickCut = (id) => {
    const next = CUTS.find((c) => c.id === id);
    setCut(next); setMm(next.mm); setBone(next.bone); setLb(String(next.lb)); setWidthIn(''); setLengthIn('');
  };
  const calibrate = (next) => {
    setCalibration(next);
    try {
      if (next) localStorage.setItem(CALIBRATION_KEY, JSON.stringify(next));
      else localStorage.removeItem(CALIBRATION_KEY);
    } catch { /* private mode: the fit still applies until the page closes */ }
  };
  const sized = p?.steak;
  return (
    <div className="sv-page">
      <SiteHeader product="Sous vide" to="/sousvide" icon="🥩" onSignIn={null} />
      <main className="sv-main">
        <h1 className="cc-h1">Sous vide steak</h1>
        <section className="sv-controls" aria-label="Steak">
          <Segmented label="Cut" items={CUTS.map((c) => ({ key: c.id, name: c.name }))} value={cut.id} onChange={pickCut} />
          <Range label={cut.shape === 'cylinder' ? 'Diameter' : 'Thickness'} value={mm} min={10} max={100} step={1}
            shown={`${fmtInches(mm)} · ${mm} mm`} onChange={setMm} />
          <div className="sv-measures">
            <Measure label="Weight, lb" value={lb} step="0.01" onChange={setLb} />
            {cut.shape !== 'cylinder' && <Measure label={slab ? 'Width, in' : 'Diameter, in'} value={widthIn} step="0.1"
              placeholder="from weight" onChange={setWidthIn} />}
            {cut.shape !== 'puck' && <Measure label="Length, in" value={lengthIn} step="0.1" placeholder="from weight" onChange={setLengthIn} />}
          </div>
          {slab && <Segmented label="Bone" items={BONES} value={bone} onChange={setBone} />}
          <Range label="Target" value={target} min={49} max={68} step={0.5}
            shown={`${fmtF(target)} · ${doneness(target)}`} onChange={setTarget} />
          <Range label="Starts at" value={start} min={0} max={30} step={0.5} shown={fmtF(start)} onChange={setStart} />
          <Range label="Hotter bath" value={boost} min={0} max={10} step={0.5}
            shown={`+${Math.round(deltaF(boost))}°F · ${fmtF(target + boost)}`} onChange={setBoost} />
          <Range label="Sear, each side" value={sear} min={0} max={120} step={15}
            shown={sear ? `${sear} s` : 'none'} onChange={setSear} />
        </section>
        <Calibrate steak={steak} calibration={calibration} onChange={calibrate} />
        {plan.status === 'error' && <p className="cc-notice cc-notice--error" role="alert">{plan.message}</p>}
        {!p && plan.status === 'loading' && <p className="cc-caption" aria-busy="true">Working out the heat…</p>}
        {p && (
          <div className={`sv-results${plan.status === 'loading' ? ' is-stale' : ''}`} aria-busy={plan.status === 'loading'}>
            {p.warnings.map((w) => <p key={w} className="cc-notice cc-notice--error" role="alert">{w}</p>)}
            <p className="cc-caption sv-basis">
              {sized.sized_by === 'weight' && `Sized from the weight as ${fmtInches(sized.width_mm ?? mm)} × ${fmtInches(sized.length_mm ?? mm)}. `}
              {sized.sized_by === 'thickness' && 'No weight or width, so this is an endless slab: it runs long unless the steak is five thicknesses wide. '}
              {p.thickness_only_minutes - p.classic.minutes > 1
                && `Thickness alone would say ${fmtMinutes(p.thickness_only_minutes)} for the classic cook. `}
              {PROBE[cut.shape === 'cylinder' ? 'cylinder' : sized.bone]}
            </p>
            <section className="sv-cards" aria-label="Methods">
              {STRATEGIES.map((s) => <Card key={s.id} strategy={s} row={p[s.id]} target={target} />)}
            </section>
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
