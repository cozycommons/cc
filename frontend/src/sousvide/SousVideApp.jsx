import React, { Suspense, use, useDeferredValue, useId, useState, useSyncExternalStore } from 'react';
import SiteHeader from '../components/SiteHeader.jsx';
import { getUrl } from '../api.js';
import PixelKitchen from './PixelKitchen.jsx';
import { Burst, Sprite } from './Sprites.jsx';
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
const COOK_KEY = 'sousvide.cook';
const LOG_KEY = 'sousvide.log';
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
// A measurement, or null when it is unknown.
const measured = (v) => (Number.isFinite(v) && v > 0 ? v : null);
// The probe log as earlier versions stored it, one "minutes, °F" line per reading,
// as [minutes, °F] pairs.
export function readLog(text) {
  return text.split('\n').map((line) => line.trim().split(/[\s,;]+/).map(Number))
    .filter((pair) => pair.length >= 2 && pair.every(Number.isFinite)).map(([min, f]) => [min, f]);
}
// The saved log: the bath it was taken in and its readings. A log from before the
// bath was saved with it takes the running cook's bath, if any.
function loadLog() {
  const saved = load(LOG_KEY);
  if (typeof saved === 'string') return { bathF: load(COOK_KEY)?.bathF ?? null, readings: readLog(saved) };
  return saved?.readings ? saved : { bathF: null, readings: [] };
}
// A cook runs for hours on a phone that locks and reloads, so the running cook, its
// probe log and the fit survive a reload. Storage can be missing (private mode); the
// page then still works until it closes.
function load(key) {
  try { return JSON.parse(localStorage.getItem(key)) ?? null; } catch { return null; }
}
function save(key, value) {
  try {
    if (value == null) localStorage.removeItem(key);
    else localStorage.setItem(key, JSON.stringify(value));
  } catch { /* private mode */ }
}
export const deltaF = (c) => c * 9 / 5;
export const fmtF = (c) => `${Math.round(toF(c))}°F`;
// A temperature range in °F, or one value when both ends round to it.
export function fmtRange([lo, hi]) {
  const [a, b] = [lo, hi].map((c) => Math.round(toF(c)));
  return a === b ? `about ${a}°F` : `about ${a} to ${b}°F`;
}
// The finished center, with its doneness only when both ends share one.
export function finish(range) {
  const [lo, hi] = range.map(doneness);
  return lo === hi ? `${fmtRange(range)}, ${lo}` : fmtRange(range);
}
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

// Whether a cook breaks the model's one food-safety rule (model.DANGER_C and
// DANGER_HOURS): a bath below SAFE_HOLD_C, for longer than SAFE_HOURS.
export const tooLong = (row) => row.bath_c < SAFE_HOLD_C && row.minutes > SAFE_HOURS * 60;

// The method to lead with: pulling from a hotter bath, unless it saves too
// little or overcooks more than the classic cook, or breaks the time rule when
// the classic cook does not. Hot, then cool is always slower than pulling; it
// is the choice when the steak has to wait.
export function recommended(plan) {
  const pull = plan.hot_and_pull;
  if (tooLong(pull) !== tooLong(plan.classic)) return tooLong(pull) ? 'classic' : 'hot_and_pull';
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

// The center and the crust `after` minutes into the rest (the sear's end), or null
// past the end of the trace.
export function restAt(trace, searS, after) {
  const bathEnd = trace.filter((p) => p.phase === 'bath').at(-1).min;
  const at = bathEnd + searS / 60 + after;
  return trace.find((p) => p.phase === 'finish' && p.min >= at - 0.5) ?? null;
}

// Cutting early is a choice a cook makes at the board: what they get if they cut
// at SLICE_EARLY instead of waiting for the center to peak. Only worth saying when
// the rest is long and the center still has a degree or more to climb.
const SLICE_EARLY = 5;
export function sliceEarly(trace, searS) {
  const rest = restMinutes(trace, searS);
  const early = restAt(trace, searS, SLICE_EARLY);
  const end = restAt(trace, searS, rest);
  if (rest < SLICE_EARLY * 2 || !early || !end || end.core - early.core < 0.5) return null;
  return { min: SLICE_EARLY, core: early.core, crust: end.surface };
}

// Minutes of the day as a clock reads, '7:05 PM'. Pure arithmetic, so a schedule
// renders the same every time without reading the current time.
export function fmtClock(minOfDay) {
  const m = ((Math.round(minOfDay) % 1440) + 1440) % 1440;
  const h = Math.floor(m / 60);
  return `${h % 12 || 12}:${String(m % 60).padStart(2, '0')} ${h < 12 ? 'AM' : 'PM'}`;
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
      // A 422 for an out-of-range measurement carries a list of field errors, not a message.
      if (!response.ok) {
        throw new Error(typeof body?.detail === 'string' ? body.detail
          : response.status === 422 ? 'A measurement is out of range. Check the weight, width and length.' : 'Could not plan the cook.');
      }
      return body;
    });
    // Recording the result on the promise lets use() read a settled plan without
    // suspending, so a screen whose plan was fetched ahead of it shows at once.
    promise.then((value) => { promise.status = 'fulfilled'; promise.value = value; },
      (reason) => { promise.status = 'rejected'; promise.reason = reason; failed.add(query); });
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
    return <p className="cc-notice cc-notice--error" role="alert">{this.state.error.message}</p>;
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
function Range({ label, value, shown, min, max, step, onChange, below }) {
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
      {below?.(draft ?? value)}
    </label>
  );
}

// A number set by tapping, never typed: a coarse and a fine step either side of the
// value. `steps` is [coarse, fine] with their button text; the caller decides what a
// step does, so a stepper can count degrees, inches or minutes of the day. The value
// is keyed so each change replays a small bump (CSS only).
const fmtStep = (n) => ({ 0.25: '¼', 0.5: '½' }[n] ?? String(n));
export function Stepper({ label, shown, note, steps, onStep, canStep = () => true, children }) {
  const button = (d, text) => (
    <button type="button" className="sv-key sv-key--step" aria-label={`${label} ${text}`} disabled={!canStep(d)}
      onClick={() => onStep(d)}>{text}</button>
  );
  const [coarse, fine] = steps;
  return (
    <div className="sv-stepper" role="group" aria-label={label}>
      <span className="cc-label">{label}</span>
      <div className="sv-stepper__row">
        {button(-coarse.d, `−${coarse.text ?? fmtStep(coarse.d)}`)}
        {button(-fine.d, `−${fine.text ?? fmtStep(fine.d)}`)}
        <output className="sv-stepper__value" aria-live="polite"><span key={shown}>{shown}</span>
          {note && <small>{note}</small>}</output>
        {button(fine.d, `+${fine.text ?? fmtStep(fine.d)}`)}
        {button(coarse.d, `+${coarse.text ?? fmtStep(coarse.d)}`)}
      </div>
      {children}
    </div>
  );
}

// value + d on the fine step's grid, inside [min, max].
export function stepValue(value, d, { min, max, fine }) {
  const next = Math.round((value + d) / fine) * fine;
  return Number(Math.min(max, Math.max(min, next)).toFixed(3));
}

// A measurement in a stepper. Unknown (null) shows `empty`, and the first tap starts
// from `base`, the value the planner would assume; `clear` returns it to unknown.
function Measure({ label, value, base, empty, unit, steps, min, max, clear, onChange }) {
  const fine = steps[1].d;
  const from = value ?? Math.round(base / fine) * fine;
  return (
    <Stepper label={label} steps={steps} shown={value == null ? empty : `${value}${unit}`}
      note={value == null ? clear.empty : null}
      canStep={(d) => (d < 0 ? from > min : from < max)}
      onStep={(d) => onChange(stepValue(from, d, { min, max, fine }))}>
      {value != null && <button type="button" className="sv-chip" onClick={() => onChange(null)}>{clear.label}</button>}
    </Stepper>
  );
}

// One method as steps a cook follows, in the order they happen.
function steps(id, row, form, plan) {
  const { target, sear } = form;
  const canWait = target >= SAFE_HOLD_C; // below this, the bath is not a safe place to hold
  const pullAt = fmtF(row.pull_core_c);
  const about = `about ${fmtMinutes(row.minutes)} in`;
  const probe = PROBE[form.cut.shape === 'cylinder' ? 'cylinder' : plan.steak.bone];
  // Where the center ends, across a weaker to stronger sear (as in the cut-open view),
  // named only when the whole range is one doneness.
  const ends = finish(row.core_peak_range_c);
  const rest = Math.max(1, Math.round(restMinutes(plan.trace[id], sear)));
  const out = [
    { key: 'bath', label: 'Set the bath to', value: fmtF(row.bath_c) },
    { key: 'probe', label: 'Thermometer tip', note: probe },
  ];
  // Cooling before the steak is ready is part of the cook; cooling at the moment it
  // is ready only matters when it can then wait.
  const coolFirst = id === 'hot_then_drop' && row.switch_minutes < row.minutes - 1;
  if (coolFirst) {
    out.push({ key: 'cool', label: 'Cool the bath to', value: fmtF(target), note: `at ${fmtMinutes(row.switch_minutes)}. Ice works.` });
  }
  if (id === 'hot_then_drop' && row.switch_minutes >= row.minutes - 1 && canWait) {
    out.push({ key: 'cool', label: 'Cool the bath to', value: fmtF(target),
      note: `when it reads ${pullAt}, ${about}. Ice works. It can then wait in the bath.` });
  } else {
    out.push({ key: 'out', label: 'Take it out at', value: pullAt,
      note: `on the thermometer, ${about}${id === 'hot_and_pull' ? '. Sear it right away.'
        : id === 'hot_then_drop' && !canWait && !coolFirst ? `. Below ${fmtF(SAFE_HOLD_C)} it can’t wait, so skip cooling the bath and sear right away.`
          : canWait ? ', or any time after.' : `. Below ${fmtF(SAFE_HOLD_C)} it can’t wait: sear right away.`}` });
  }
  // What a longer sear changes: the layer under the crust that goes past the target.
  const under = row.overcooked_mm > 0 ? `${fmtDepth(row.overcooked_mm)} a side cooks past ${doneness(target)}` : `nothing cooks past ${doneness(target)}`;
  const early = sliceEarly(plan.trace[id], sear);
  const sooner = early ? ` Cut it at ${early.min} min and the center is ${fmtF(early.core)}, ${doneness(early.core)}.` : '';
  const crust = early ? ` A full rest leaves the crust about ${fmtF(early.crust)}.` : '';
  out.push(sear
    ? { key: 'sear', label: 'Sear', value: `${sear} s a side`, note: `then rest ${rest} min. The center ends ${ends}.${sooner}`,
      more: `Under the crust, ${under}. A longer sear browns more and cooks that layer deeper.${crust}` }
    : { key: 'sear', label: 'Rest', value: `${rest} min`, note: `The center ends ${ends}.${sooner}` });
  return out;
}

function tradeoff(id, row, target) {
  const canWait = target >= SAFE_HOLD_C;
  const saved = row.saved_minutes >= 1 ? `${fmtMinutes(row.saved_minutes)} faster than classic` : 'No faster than classic';
  if (id === 'hot_and_pull') return `Fastest of the three: ${saved}. It can’t wait: take it out on time and sear straight away.`;
  if (id === 'hot_then_drop') {
    return canWait ? `${saved}, slower than pulling, but it can wait once the bath is cool.` : `${saved}, slower than pulling.`;
  }
  return canWait ? 'The slowest and the easiest: it can wait in the bath once it’s done.' : 'The slowest and the easiest.';
}

// The time rule, read off the coolest the bath gets. The page only states it when
// it applies, and claims nothing about safety when it does not.
function safety(id, row, target) {
  const coolest = id === 'hot_and_pull' ? row.bath_c : target;
  if (coolest >= SAFE_HOLD_C) return null;
  return {
    ok: row.minutes <= SAFE_HOURS * 60,
    text: `Below ${fmtF(SAFE_HOLD_C)}, keep the whole cook under ${SAFE_HOURS} h. This one takes ${fmtMinutes(row.minutes)}.`,
  };
}

// The cook's milestones, in minutes from the bag going in. Eating time adds both
// sides of the sear and the rest the steps ask for.
export function milestones(id, row, form, plan) {
  const { target, sear } = form;
  const pullAt = fmtF(row.pull_core_c);
  const canWait = target >= SAFE_HOLD_C;
  const rest = Math.max(1, Math.round(restMinutes(plan.trace[id], sear)));
  const out = [{ key: 'in', at: 0, label: `Into the ${fmtF(row.bath_c)} bath` }];
  if (id === 'hot_then_drop' && row.switch_minutes < row.minutes - 1) {
    out.push({ key: 'cool', at: row.switch_minutes, label: `Cool the bath to ${fmtF(target)}` });
  }
  const holds = canWait && id !== 'hot_and_pull';
  out.push({ key: 'out', at: row.minutes, label: holds ? `Ready at ${pullAt}, or any time after` : `Out at ${pullAt}, sear right away` });
  out.push({ key: 'eat', at: row.minutes + (2 * sear) / 60 + rest, label: sear ? 'Sear, rest, eat' : 'Rest, eat' });
  return out;
}

// The earliest dinner a cook taking `total` minutes allows if it starts now, on a
// quarter hour. Read when a stepper is tapped, never during render.
const earliestEat = (total) => {
  const now = new Date();
  return Math.ceil((now.getHours() * 60 + now.getMinutes() + total) / 15) * 15;
};
const EAT_STEPS = [{ d: 60, text: '1 h' }, { d: 15, text: '15' }];
const READING_STEPS = [{ d: 5 }, { d: 1 }];

// When each step happens: counted from now until the cook starts, or back from a
// dinner time, or on the clock once the bag is in. Nothing here ticks; the clock
// times come from the moment Start was pressed, and the thermometer decides.
// `eatAt` is dinner as minutes of the day, or null for "start now".
function Schedule({ id, row, form, plan, cook, readings, party, eatAt, onEatAt, onStart, onEnd, onReading }) {
  // The thermometer stepper starts from the last reading, or the steak's start.
  const [reading, setReading] = useState(null);
  const marks = milestones(id, row, form, plan);
  const total = marks.at(-1).at;
  const startMin = cook ? cook.startMin : eatAt != null ? eatAt - total : null;
  const when = (m) => (startMin == null ? (m ? `+${fmtMinutes(m)}` : 'Now') : fmtClock(startMin + m));
  const last = readings.at(-1)?.[1];
  const shownF = reading ?? last ?? Math.round(toF(form.start));
  const stepEat = (d) => {
    const earliest = earliestEat(total);
    onEatAt(Math.max(earliest, eatAt == null ? earliest + Math.max(0, d) : eatAt + d));
  };
  const log = () => { onReading(shownF); setReading(null); };
  // The thermometer has reached the pull (or cool) mark: the cook's big moment.
  const ready = cook && last != null && last >= Math.round(toF(row.pull_core_c));
  return (
    <section className={`sv-when${cook ? ' is-cooking' : ''}`} aria-label="When">
      <div className="sv-when__head">
        {cook
          ? <><span className="cc-label">Cooking since {fmtClock(cook.startMin)}</span>
            <button type="button" className="sv-key sv-key--quiet" onClick={onEnd}>End cook</button></>
          : <>
            <Stepper label="Eat at" steps={EAT_STEPS} shown={eatAt == null ? 'ASAP' : fmtClock(eatAt)}
              canStep={(d) => d > 0 || eatAt != null} onStep={stepEat}>
              {eatAt != null && <button type="button" className="sv-chip" onClick={() => onEatAt(null)}>As soon as I can</button>}
            </Stepper>
            <button type="button" className="sv-key sv-key--go sv-when__start" onClick={() => onStart(id, row)}>
              <Sprite name="flame" scale={2} />Start cook</button></>}
      </div>
      <ol className="sv-when__list">
        {marks.map((m) => <li key={m.key}><time>{when(m.at)}</time><span>{m.label}</span></li>)}
      </ol>
      {cook ? (
        <div className="sv-when__log">
          <Stepper label="Thermometer reads, °F" steps={READING_STEPS} shown={`${shownF}°F`}
            canStep={(d) => (d < 0 ? shownF > 32 : shownF < 212)}
            onStep={(d) => setReading(stepValue(shownF, d, { min: 32, max: 212, fine: 1 }))} />
          <button type="button" className="sv-key sv-key--gold sv-when__logbtn" onClick={log}>
            <Sprite name="thermo" scale={2} />Log</button>
          {ready && <p className="sv-ready" key={`ready-${readings.length}`}><Sprite name="star" scale={3} />
            {marks.find((m) => m.key === 'out')?.label ?? `Cool the bath to ${fmtF(form.target)}`}</p>}
          <p className="cc-help">{readings.length
            ? `${readings.length} reading${readings.length === 1 ? '' : 's'} so far, saved in Learn, under “Tune to your kitchen”.`
            : 'Log one now, then every 10 minutes or so. The log tunes the planner to your kitchen.'}</p>
        </div>
      ) : <p className="cc-help">Estimates: the thermometer has the last word.</p>}
      {party > 0 && <Burst key={party} />}
    </section>
  );
}

const METHOD_ICON = { classic: 'pot', hot_and_pull: 'flame', hot_then_drop: 'ice' };
const STEP_ICON = { bath: 'pot', probe: 'thermo', cool: 'ice', out: 'ribeye', sear: 'flame' };

// The plan screen, or the cooking screen once a cook runs. The picked method and
// dinner time live in the page, so they survive a trip to another screen.
function Answer({ form, stale, cook, readings, party, picked, onPick, eatAt, onEatAt, onStart, onEnd, onReading }) {
  const p = use(planFor(queryOf(form)));
  const best = recommended(p);
  // A running cook keeps the method it started with.
  const id = cook?.method ?? picked ?? best;
  const row = p[id];
  const strategy = STRATEGIES.find((s) => s.id === id);
  const safe = safety(id, row, form.target);
  // Before the cook, the schedule follows the steps it times; during it, the clock
  // and the thermometer log are what the cook needs first.
  const schedule = <Schedule id={id} row={row} form={form} plan={p} cook={cook} readings={readings} party={party}
    eatAt={eatAt} onEatAt={onEatAt} onStart={onStart} onEnd={onEnd} onReading={onReading} />;
  return (
    <section className={`sv-answer${cook ? ' is-cooking' : ''}${stale ? ' is-stale' : ''}`} aria-label="What to do" aria-busy={stale}>
      {!cook && <Segmented label="Method" showLabel={false} className="sv-methods" value={id} onChange={onPick}
        items={STRATEGIES.map((s) => ({
          key: s.id, label: `${s.name}, ${fmtMinutes(p[s.id].minutes)}`,
          name: <><Sprite name={METHOD_ICON[s.id]} scale={2} /><b>{fmtMinutes(p[s.id].minutes)}</b><span>{s.name}</span></>,
        }))} />}
      <header className="sv-answer__head">
        <h2 className="cc-h3">{strategy.name}</h2>
        {id === best && !cook && <span className="cc-badge cc-badge--soft">Recommended</span>}
      </header>
      {cook && schedule}
      <ol className="sv-steps">
        {steps(id, row, form, p).map((s) => (
          <li key={s.key} data-step={s.key}>
            <Sprite name={STEP_ICON[s.key]} scale={2} className="sv-steps__icon" />
            <span className="cc-label">{s.label}</span>
            {s.value && <b>{s.value}</b>}
            {s.note && <span className="sv-steps__note">{s.note}</span>}
            {s.more && <span className="sv-steps__more">{s.more}</span>}
          </li>
        ))}
      </ol>
      {!cook && schedule}
      <p className="sv-answer__trade">{tradeoff(id, row, form.target)}</p>
      {safe && (safe.ok
        ? <p className="cc-help sv-answer__safe">{safe.text}</p>
        : <p className="cc-notice cc-notice--error" role="alert">{safe.text}</p>)}
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
// The log is the cook-along's readings, taken in the bath the cook started with.
function Calibrate({ steak, calibration, onChange, log, onDelete }) {
  const [state, setState] = useState({ status: 'idle' });
  const { bathF, readings } = log;
  const fit = async () => {
    setState({ status: 'loading' });
    try {
      const response = await fetch(`${getUrl()}/sousvide/calibrate`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ ...steak, bath_c: toC(Number(bathF)), readings: readings.map(([min, f]) => [min, toC(f)]), fit_h: true }),
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
        <p className="cc-help">Start a cook and log the thermometer every few minutes through it, in a bath held at one
          temperature, with the steak set as you measured it. Three readings or more fit the planner to your kitchen.</p>
        {readings.length ? (
          <ol className="sv-readings" aria-label="Readings">
            {readings.map(([min, f], i) => (
              <li key={`${i}-${min}`}>
                <Sprite name="thermo" scale={2} />
                <span><b>{f}°F</b> at {fmtMinutes(min)}</span>
                <button type="button" className="sv-key sv-key--x" aria-label={`Delete ${f}°F at ${fmtMinutes(min)}`}
                  onClick={() => onDelete(i)}>×</button>
              </li>
            ))}
          </ol>
        ) : <p className="cc-caption">No readings yet.</p>}
        {bathF != null && readings.length > 0 && <p className="cc-caption">Bath {bathF}°F, from the cook.</p>}
        <div className="cc-button-row">
          <button type="button" className="sv-key sv-key--go" disabled={readings.length < 3 || bathF == null || state.status === 'loading'} onClick={fit}>
            Fit {readings.length} readings</button>
          {calibration && <button type="button" className="sv-key sv-key--quiet" onClick={() => { onChange(null); setState({ status: 'idle' }); }}>
            Back to defaults</button>}
        </div>
        {state.status === 'error' && <p className="cc-notice cc-notice--error" role="alert">{state.message}</p>}
        {f && (
          <div role="status" className="sv-calibrate__fit">
            <Burst />
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
          return (
            <Slice key={s.id} profile={p.profile[s.id]} label={s.name}
              note={`center ${fmtRange(p[s.id].core_peak_range_c)}, ${fmtDepth(p[s.id].overcooked_mm)} past ${done} under each side`} />
          );
        })}
        <p className="cc-help">Estimates. The center’s range runs from a weaker to a stronger sear than assumed; a harder sear can land outside it.</p>
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

// Measuring with a finger, for a cook without a ruler. An adult index finger is
// about 23 mm from the tip to its first crease, 46 mm to the second and 19 mm wide
// laid flat; hands differ by about 15 %.
const FINGER_MM = 19;
const CREASE_MM = 23;
const FINGER_SPREAD = 0.15;
// Cook time grows about as thickness squared, so a thickness off by x% is a time off by about 2x%.
const TIME_PER_THICKNESS = 2;
const PARTS = { 0.25: '¼', 0.5: '½', 0.75: '¾' };
// 1.5 as '1½', 0.75 as '¾'.
export const fmtCount = (n) => `${Math.floor(n) || ''}${PARTS[n % 1] ?? ''}`;

export const FINGER_WAYS = [
  {
    key: 'crease', name: 'Creases',
    steps: ['Lay the steak flat on the board.', 'Stand your index finger up beside it, fingertip on the board.',
      'Where does the top of the steak reach on your finger?'],
    marks: [
      { key: 'half', name: '½', where: 'halfway to the first crease', mm: Math.round(CREASE_MM / 2) },
      { key: 'first', name: '1st', where: 'the first crease', mm: CREASE_MM },
      { key: 'between', name: '1½', where: 'between the creases', mm: Math.round(CREASE_MM * 1.5) },
      { key: 'second', name: '2nd', where: 'the second crease', mm: CREASE_MM * 2 },
      { key: 'past', name: '2½', where: 'past the second crease', mm: Math.round(CREASE_MM * 2.5) },
    ],
  },
  {
    key: 'stack', name: 'Stacked',
    steps: ['Lay the steak flat on the board.', 'Lay fingers flat against its side, one above the other, the bottom one on the board.',
      'How many fingers tall is it?'],
    marks: [1, 1.5, 2, 2.5, 3, 3.5].map((n) => ({
      key: String(n), name: fmtCount(n), where: `${fmtCount(n)} finger${n === 1 ? '' : 's'} tall`, mm: Math.round(FINGER_MM * n),
    })),
  },
];

// The steak's side on the board with a finger beside it, one unit to the millimetre,
// so the picture is to scale and shows the thickness picked: a finger standing with
// its creases marked, or fingers laid flat and stacked. A gold line marks the top.
const SIDE_H = 112;
function FingerPicture({ way, mm }) {
  const base = SIDE_H - 6;
  const tall = Math.min(Math.max(mm, 8), 90);
  const top = base - tall;
  const ink = '#2b1d1a';
  const skin = '#f0b98d';
  const shadow = '#c98a63';
  const fingers = Math.min(Math.ceil(tall / FINGER_MM - 0.05), 5);
  return (
    <svg className="sv-ruler__pic" viewBox={`0 0 160 ${SIDE_H}`} shapeRendering="crispEdges" role="img"
      aria-label={way.key === 'crease' ? 'An index finger standing beside the steak, its two creases marked' : 'Fingers laid flat and stacked beside the steak'}>
      <rect x="0" y={base} width="160" height="6" fill="#8b5a2b" />
      <rect x="0" y={base + 5} width="160" height="1" fill="#5e3c1c" />
      <rect x="8" y={top} width="72" height={tall} fill={ink} />
      <rect x="10" y={top + 2} width="68" height={tall - 4} fill="#c4344a" />
      <rect x="10" y={top + 2} width="68" height="3" fill="#7a3f1f" />
      <rect x="10" y={base - 5} width="68" height="3" fill="#7a3f1f" />
      <rect x="2" y={top - 1} width={way.key === 'crease' ? 114 : 156} height="2" fill="#ffc531" />
      {way.key === 'crease' ? (
        <g>
          <rect x="94" y={base - 88} width="22" height="88" fill={ink} />
          <rect x="96" y={base - 86} width="18" height="86" fill={skin} />
          <rect x="110" y={base - 86} width="4" height="86" fill={shadow} />
          {[1, 2].map((n) => (
            <g key={n}>
              <rect x="96" y={base - n * CREASE_MM - 1} width="18" height="2" fill="#8a4f33" />
              <text x="121" y={base - n * CREASE_MM + 4} className="sv-ruler__note">{n === 1 ? '1st' : '2nd'}</text>
            </g>
          ))}
        </g>
      ) : (
        Array.from({ length: fingers }, (_, i) => {
          const y = base - (i + 1) * FINGER_MM;
          return (
            <g key={i}>
              <rect x="86" y={y} width="66" height={FINGER_MM} fill={ink} />
              <rect x="88" y={y + 2} width="62" height={FINGER_MM - 4} fill={skin} />
              <rect x="88" y={y + FINGER_MM - 6} width="62" height="4" fill={shadow} />
              <rect x="140" y={y + 4} width="8" height="7" fill="#f8dccb" />
            </g>
          );
        })
      )}
    </svg>
  );
}

// Thickness without a ruler: a finger's creases or fingers stacked. Each pick
// sets the thickness directly; the slider above shows the result.
function RulerGuide({ mm, onChange }) {
  const [key, setKey] = useState('crease');
  const way = FINGER_WAYS.find((w) => w.key === key);
  const picked = way.marks.find((m) => m.mm === mm);
  return (
    <details className="cc-accordion sv-ruler">
      <summary>No ruler? Measure with your finger</summary>
      <div className="cc-accordion__content sv-ruler__body">
        <Segmented label="How" showLabel={false} value={key} onChange={setKey}
          items={FINGER_WAYS.map((w) => ({ key: w.key, label: w.name, name: <><Sprite name="finger" scale={2} />{w.name}</> }))} />
        <FingerPicture way={way} mm={mm} />
        <ol className="sv-ruler__steps">{way.steps.map((step) => <li key={step}>{step}</li>)}</ol>
        <Segmented label={key === 'crease' ? 'Where it reaches' : 'How many fingers'} showLabel={false}
          className="sv-seg sv-ruler__counts" value={picked?.key} onChange={(k) => onChange(way.marks.find((m) => m.key === k).mm)}
          items={way.marks.map((m) => ({ key: m.key, name: m.name, label: m.where }))} />
        <p className="cc-help">
          {picked ? `Up to ${picked.where.replace(/ tall$/, '')}: about ${fmtInches(mm)}. ` : 'Tap where it reaches. '}
          Fingers differ by about {Math.round(FINGER_SPREAD * 100)}%, about {Math.round(FINGER_SPREAD * TIME_PER_THICKNESS * 100)}% on
          cook time: close enough to plan, and the thermometer has the last word.
        </p>
      </div>
    </details>
  );
}

const formFor = (cut, rest) => ({
  ...rest, cut, mm: cut.mm, bone: cut.bone, lb: cut.lb, widthIn: null, lengthIn: null,
});

// model.sized, in inches: the sides nobody measured, filled in from the weight, so a
// side's stepper starts where the planner already is.
const MEAT_DENSITY = 1050; // kg/m³, model.MEAT_DENSITY
const PLAN_ASPECT = 1.3; // model.PLAN_ASPECT
export function sizedIn({ cut, mm, lb, widthIn, lengthIn }) {
  const width = widthIn && widthIn * MM_PER_IN;
  const length = lengthIn && lengthIn * MM_PER_IN;
  const out = (w, l) => ({ width: w && w / MM_PER_IN, length: l && l / MM_PER_IN });
  if (!lb) return out(width, length);
  const volume = (lb * G_PER_LB) / 1000 / MEAT_DENSITY * 1e9;
  if (cut.shape === 'cylinder') return out(null, length || volume / (Math.PI * (mm / 2) ** 2));
  const area = volume / mm;
  if (cut.shape === 'puck') return out(width || (4 * area / Math.PI) ** 0.5, null);
  if (width || length) return out(width || area / length, length || area / width);
  const w = (area / PLAN_ASPECT) ** 0.5;
  return out(w, w * PLAN_ASPECT);
}

// The targets from rare to well done as blocks of meat colour, the chosen one lifted.
function DonenessStrip({ c }) {
  const blocks = Array.from({ length: 20 }, (_, i) => 49 + i);
  const at = Math.round(c);
  return (
    <span className="sv-doneness" aria-hidden="true">
      {blocks.map((b) => <i key={b} className={b === at ? 'is-on' : undefined} style={{ background: shade(b + 0.5) }} />)}
    </span>
  );
}

const WEIGHT_STEPS = [{ d: 0.5 }, { d: 0.05, text: '.05' }];
const SIDE_STEPS = [{ d: 0.5 }, { d: 0.1, text: '.1' }];

const startNote = (c) => (c <= 7 ? ' · fridge' : c >= 18 ? ' · room temp' : '');

// The page is a flow of screens, and the screen lives in the URL hash so the
// phone's back button and browser history move between them. A step forward
// pushes a history entry and marks it, so Back can return through history when
// the entry before is this flow, and replaces the entry when it is not (a link
// straight to #plan). pushState fires no event, so the flow tells its own
// subscribers; the browser's back and forward arrive as popstate or hashchange.
export const SCREENS = ['steak', 'cook', 'plan', 'cooking', 'learn'];
const hashListeners = new Set();
function subscribeHash(onChange) {
  hashListeners.add(onChange);
  window.addEventListener('popstate', onChange);
  window.addEventListener('hashchange', onChange);
  return () => {
    hashListeners.delete(onChange);
    window.removeEventListener('popstate', onChange);
    window.removeEventListener('hashchange', onChange);
  };
}
const readHash = () => window.location.hash.slice(1);
const noHash = () => '';
export function go(screen, { replace = false } = {}) {
  const state = window.history.state;
  window.history[replace ? 'replaceState' : 'pushState']({ ...state, svFlow: replace ? Boolean(state?.svFlow) : true }, '', `#${screen}`);
  if (document.scrollingElement) document.scrollingElement.scrollTop = 0;
  hashListeners.forEach((notify) => notify());
}
function goBack(fallback) {
  if (window.history.state?.svFlow) window.history.back();
  else go(fallback, { replace: true });
}

// Which screen a hash shows. A running cook owns the plan screen (and an empty
// hash, so a reload lands on it); the steak, the cook and Learn stay reachable
// mid-cook. Without a cook, #cooking shows the plan.
export function screenFor(hash, cooking) {
  const screen = SCREENS.includes(hash) ? hash : null;
  if (cooking) return !screen || screen === 'plan' ? 'cooking' : screen;
  if (screen === 'cooking') return 'plan';
  return screen ?? 'steak';
}
// The progress bar's steps; Learn sits on the step it was opened from.
const PROGRESS = ['steak', 'cook', 'plan', 'cooking'];
const ORDER = Object.fromEntries(SCREENS.map((s, i) => [s, i]));
const HEADINGS = { steak: 'Your steak', cook: 'Your cook', plan: 'The plan', cooking: 'Cooking', learn: 'Learn' };

// Moves focus to a new screen's heading, for keyboards and screen readers. It is
// one function for the page's life, so React calls it once per mounted heading.
const focusHeading = (el) => el?.focus({ preventScroll: true });

// The steak, its cook and the plan's two choices are remembered across a reload,
// since the cook runs for hours on a phone that locks.
const FORM_KEY = 'sousvide.steak';
function loadForm() {
  const saved = load(FORM_KEY);
  const cut = CUTS.find((c) => c.id === saved?.cut) ?? CUTS[0];
  const base = formFor(cut, { start: 5, target: 54.5, boost: 3, sear: 45 });
  const pick = (key, ok) => (ok(saved?.[key]) ? { [key]: saved[key] } : {});
  const num = (v) => typeof v === 'number' && Number.isFinite(v);
  const numOrNull = (v) => v === null || num(v);
  return {
    ...base,
    ...['mm', 'start', 'target', 'boost', 'sear'].reduce((o, k) => ({ ...o, ...pick(k, num) }), {}),
    ...['lb', 'widthIn', 'lengthIn'].reduce((o, k) => ({ ...o, ...pick(k, numOrNull) }), {}),
    ...pick('bone', (v) => BONES.some((b) => b.key === v)),
    calibration: load(CALIBRATION_KEY),
  };
}
const saveForm = ({ cut, calibration, ...rest }) => save(FORM_KEY, { ...rest, cut: cut.id });

// "2″ bone-in ribeye, 2.94 lb · 130°F": the steak and its target, on one chip.
export function summary(form) {
  const lb = measured(form.lb);
  const name = form.cut.name[0].toLowerCase() + form.cut.name.slice(1);
  return `${fmtDepth(form.mm)} ${name}${lb ? `, ${lb} lb` : ''} · ${fmtF(form.target)}`;
}

export default function SousVideApp() {
  const [form, setFormState] = useState(loadForm);
  // The running cook ({ method, startedAt ms, startMin of the day, bath °F }) and its
  // probe log, the same text the calibration fits.
  const [cook, setCook] = useState(() => load(COOK_KEY));
  const [log, setLogState] = useState(loadLog);
  // Counts the cook's milestones (start, each reading); each one replays a burst.
  const [party, setParty] = useState(0);
  // The plan screen's method tab and dinner time.
  const [picked, setPicked] = useState(null);
  const [eatAt, setEatAt] = useState(null);
  const hash = useSyncExternalStore(subscribeHash, readHash, noHash);
  const screen = screenFor(hash, cook != null);
  // Which way the last screen change went, kept during render: forward slides in
  // from the right, back from the left, and the first screen just appears.
  const [trail, setTrail] = useState({ screen, dir: 'none' });
  if (trail.screen !== screen) setTrail({ screen, dir: ORDER[screen] > ORDER[trail.screen] ? 'fwd' : 'back' });
  const dir = trail.screen === screen ? trail.dir : 'none';

  const setForm = (next) => { setFormState(next); saveForm(next); };
  const setLog = (next) => { setLogState(next); save(LOG_KEY, next.readings.length ? next : null); };
  const startCook = (method, row) => {
    const now = new Date();
    const next = { method, startedAt: now.getTime(), startMin: now.getHours() * 60 + now.getMinutes(),
      bathF: Math.round(toF(row.bath_c) * 2) / 2 };
    setCook(next); save(COOK_KEY, next);
    setLog({ bathF: next.bathF, readings: [] }); // a new cook is a new log
    setParty((n) => n + 1);
    // The cook takes the plan's place in history, so Back never returns to a plan already started.
    go('cooking', { replace: true });
  };
  const endCook = () => { setCook(null); save(COOK_KEY, null); go('plan', { replace: true }); };
  const addReading = (f) => {
    const min = Math.round((Date.now() - cook.startedAt) / 6000) / 10;
    setLog({ bathF: log.bathF ?? Number(cook.bathF), readings: [...log.readings, [min, f]] });
    setParty((n) => n + 1);
  };
  const deleteReading = (i) => setLog({ ...log, readings: log.readings.filter((_, k) => k !== i) });
  // The last plan stays on screen, dimmed, while the next one loads.
  const shown = useDeferredValue(form);
  const set = (key) => (value) => setForm({ ...form, [key]: value });
  const pickCut = (id) => setForm(formFor(CUTS.find((c) => c.id === id), form));
  const calibrate = (next) => {
    setFormState({ ...form, calibration: next });
    save(CALIBRATION_KEY, next);
  };
  const query = queryOf(shown);
  // Ask for the plan as soon as the steak and cook settle, so it is in flight or
  // cached by the time the plan screen shows. planFor shares one request per plan.
  planFor(queryOf(form));

  const { cut, target } = form;
  const slab = cut.shape === 'slab';
  const lb = measured(form.lb);
  const sides = sizedIn(form);
  const fromWeight = lb ? { empty: 'from weight', label: 'From weight' } : { empty: 'unknown', label: 'Unknown' };
  const loading = <p className="cc-caption sv-loading" aria-busy="true"><Sprite name="pot" scale={3} />Working out the heat…</p>;
  const answer = (
    <PlanError query={query}>
      <Suspense fallback={loading}>
        <Answer form={shown} stale={shown !== form} cook={cook} readings={log.readings} party={party}
          picked={picked} onPick={setPicked} eatAt={eatAt} onEatAt={setEatAt}
          onStart={startCook} onEnd={endCook} onReading={addReading} />
      </Suspense>
    </PlanError>
  );
  const step = PROGRESS.indexOf(screen === 'learn' ? (cook ? 'cooking' : 'plan') : screen) + 1;
  const toPlan = cook ? 'cooking' : 'plan';

  const body = {
    steak: (
      <section className="sv-form sv-form--steak" aria-label="Steak">
        <div className="sv-form__col">
          <Segmented label="Cut" className="sv-cuts" value={cut.id} onChange={pickCut}
            items={CUTS.map((c) => ({ key: c.id, label: c.name, name: <><Sprite name={c.id} scale={3} /><span>{c.name}</span></> }))} />
          <Range label={cut.shape === 'cylinder' ? 'Diameter' : 'Thickness'} value={form.mm} min={10} max={100} step={1}
            shown={(mm) => `${fmtInches(mm)} · ${mm} mm`} onChange={set('mm')} />
          <RulerGuide mm={form.mm} onChange={set('mm')} />
        </div>
        <div className="sv-form__col">
          <Measure label="Weight, lb" value={form.lb} base={cut.lb} unit=" lb" empty="unknown" steps={WEIGHT_STEPS}
            min={0.15} max={11} clear={{ empty: 'sized by thickness', label: 'Don’t know' }} onChange={set('lb')} />
          {slab && <Segmented label="Bone" items={BONES} value={form.bone} onChange={set('bone')} />}
          <Range label="Starts at" value={form.start} min={0} max={30} step={0.5}
            shown={(c) => `${fmtF(c)}${startNote(c)}`} onChange={set('start')} />
          <details className="cc-accordion sv-more">
            <summary>More: width and length</summary>
            <div className="cc-accordion__content sv-measures">
              <p className="cc-help">Optional. The weight already sizes the steak; a ruler across the top sharpens it.</p>
              {cut.shape !== 'cylinder' && <Measure label={slab ? 'Width, in' : 'Diameter, in'} value={form.widthIn}
                base={sides.width ?? cut.mm / MM_PER_IN * 3} unit="″" steps={SIDE_STEPS} min={0.8} max={15}
                empty={sides.width ? `≈${sides.width.toFixed(1)}″` : 'unknown'} clear={fromWeight} onChange={set('widthIn')} />}
              {cut.shape !== 'puck' && <Measure label="Length, in" value={form.lengthIn}
                base={sides.length ?? cut.mm / MM_PER_IN * 4} unit="″" steps={SIDE_STEPS} min={0.8} max={23}
                empty={sides.length ? `≈${sides.length.toFixed(1)}″` : 'unknown'} clear={fromWeight} onChange={set('lengthIn')} />}
            </div>
          </details>
        </div>
      </section>
    ),
    cook: (
      <section className="sv-form sv-form--cook" aria-label="Cook">
        <Range label="Doneness" value={target} min={49} max={68} step={0.5}
          shown={(c) => `${fmtF(c)} · ${doneness(c)}`} onChange={set('target')} below={(c) => <DonenessStrip c={c} />} />
        <Range label="Hot bath, for the faster methods" value={form.boost} min={0} max={10} step={0.5}
          shown={(b) => `${fmtF(target + b)} · +${Math.round(toF(target + b)) - Math.round(toF(target))}°F`} onChange={set('boost')} />
        <Range label="Sear, each side" value={form.sear} min={0} max={120} step={15}
          shown={(v) => (v ? `${v} s` : 'none')} onChange={set('sear')} />
      </section>
    ),
    plan: answer,
    cooking: answer,
    learn: (
      <>
        <PlanError query={query}>
          <Suspense fallback={loading}>
            <Details form={shown} stale={shown !== form} />
          </Suspense>
        </PlanError>
        <Calibrate steak={steakParams(form)} calibration={form.calibration} onChange={calibrate}
          log={log} onDelete={deleteReading} />
      </>
    ),
  }[screen];

  // Each screen's way back and way on, in the sticky bar at the bottom.
  const nav = {
    steak: { next: cook ? { label: 'Back to the cook', to: 'cooking' } : { label: 'Next', to: 'cook' } },
    cook: { back: 'steak', next: cook ? { label: 'Back to the cook', to: 'cooking' } : { label: 'See the plan', to: 'plan' } },
    plan: { back: 'cook', next: { label: 'Learn more', to: 'learn', quiet: true } },
    cooking: { next: { label: 'Learn and tune', to: 'learn', quiet: true } },
    learn: { back: toPlan },
  }[screen];

  return (
    <div className="sv-page">
      <SiteHeader product="Sous vide" to="/sousvide" icon="🥩" onSignIn={null} />
      <main className="sv-main">
        <div className="sv-progress" role="progressbar" aria-label="Progress" aria-valuemin={1} aria-valuemax={PROGRESS.length}
          aria-valuenow={step} aria-valuetext={`${HEADINGS[PROGRESS[step - 1]]}, step ${step} of ${PROGRESS.length}`}>
          <i style={{ transform: `scaleX(${step / PROGRESS.length})` }} />
        </div>
        <div key={screen} className={`sv-screen sv-screen--${screen} is-${dir}`}>
          <header className="sv-screen__head">
            <h1 className="cc-h1 sv-title" tabIndex={-1} ref={dir === 'none' ? undefined : focusHeading}>
              {screen === 'steak' && <Sprite key={cut.id} name={cut.id} scale={4} className="sv-title__cut" />}
              {HEADINGS[screen]}
            </h1>
            {screen !== 'steak' && (
              <button type="button" className="sv-summary" aria-label={`${summary(form)}. Change the steak`}
                onClick={() => go('steak')}>
                <Sprite name={cut.id} scale={2} /><span>{summary(form)}</span><b aria-hidden="true">Edit</b>
              </button>
            )}
          </header>
          {body}
        </div>
        <nav className="sv-nav" aria-label="Screens">
          {nav.back && <button type="button" className="sv-key sv-nav__back" onClick={() => goBack(nav.back)}>Back</button>}
          {nav.next && (
            <button type="button" className={`sv-key ${nav.next.quiet ? 'sv-nav__more' : 'sv-key--go sv-nav__next'}`}
              onClick={() => go(nav.next.to)}>{nav.next.label}</button>
          )}
        </nav>
      </main>
    </div>
  );
}
