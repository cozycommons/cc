import React, { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { STRATEGIES, fmtMinutes, shade, toF } from './SousVideApp.jsx';

// A pixel-art replay of one cook from the plan's trace: the bag in the bath, the
// pan, the board, and a cross-section that fills in as each layer peaks. The
// canvas is drawn at W x H and scaled up with image-rendering: pixelated.
export const W = 200;
export const H = 112;
const PLAY_MS = 14000; // a whole cook, any length, replays in this long
const FRAME_MS = 83; // about 12 fps

const C = {
  wall: '#e7dcc5', tile: '#dccfb4', counter: '#694b36', plank: '#5a3f2d', edge: '#8a6448',
  ink: '#3d2f29', soft: '#6f6256', paper: '#f2eadb', butter: '#f0c477', amber: '#d39155',
  clay: '#b76845', moss: '#69755a', mossDark: '#465243', steel: '#9aa3a2', steelDark: '#6e7b7e',
  water: '#8fb3b6', waterDeep: '#6f9599', foam: '#d9ebe8', iron: '#2d2422', ironHi: '#4a3d39',
  board: '#c99b6d', boardDark: '#a77b52', fat: '#f3e4cf', bone: '#efe6d2', marrow: '#c98f7a', cat: '#8a6f5a', catDark: '#5e4a3c',
};

// 3x5 digits for the circulator and the clock.
const GLYPHS = {
  0: '111101101101111', 1: '010110010010111', 2: '111001111100111', 3: '111001111001111',
  4: '101101111001001', 5: '111100111001111', 6: '111100111101111', 7: '111001001001001',
  8: '111101111101111', 9: '111101111001111', F: '111100110100100', ':': '0',
};

// Temperature at fractional radius rho (0 centre, 1 surface) from the trace's
// core, middle (about half way out) and surface readings.
export function tempAt(point, rho) {
  return rho <= 0.5
    ? point.core + (point.mid - point.core) * (rho / 0.5)
    : point.mid + (point.surface - point.mid) * ((rho - 0.5) / 0.5);
}

// The trace point at minute t, linearly between readings.
export function pointAt(trace, t) {
  if (t <= trace[0].min) return trace[0];
  for (let i = 1; i < trace.length; i += 1) {
    const a = trace[i - 1];
    const b = trace[i];
    if (t <= b.min) {
      const f = (t - a.min) / (b.min - a.min || 1);
      const mix = (k) => a[k] + (b[k] - a[k]) * f;
      return { min: t, phase: b.phase, core: mix('core'), mid: mix('mid'), surface: mix('surface') };
    }
  }
  return trace.at(-1);
}

// Peak temperature so far at each of n radii, centre first.
export function peaksAt(trace, t, n) {
  const peaks = Array(n).fill(-Infinity);
  const visit = (p) => { for (let i = 0; i < n; i += 1) peaks[i] = Math.max(peaks[i], tempAt(p, i / (n - 1))); };
  for (const p of trace) { if (p.min > t) break; visit(p); }
  visit(pointAt(trace, t));
  return peaks;
}

// Where the cook is at minute t: in the bath, searing, or resting.
export function sceneAt(trace, t, searS) {
  const bathEnd = trace.filter((p) => p.phase === 'bath').at(-1)?.min ?? 0;
  if (t <= bathEnd) return 'bath';
  return t - bathEnd <= searS / 60 ? 'sear' : 'rest';
}

function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let x = Math.imul(a ^ (a >>> 15), 1 | a);
    x = (x + Math.imul(x ^ (x >>> 7), 61 | x)) ^ x;
    return ((x ^ (x >>> 14)) >>> 0) / 4294967296;
  };
}

export function painter(ctx) {
  const px = (x, y, w, h, color) => { ctx.fillStyle = color; ctx.fillRect(Math.round(x), Math.round(y), w, h); };
  const text = (s, x, y, color) => {
    let cx = x;
    for (const ch of String(s)) {
      const g = GLYPHS[ch];
      if (!g) { cx += 2; continue; }
      if (ch === ':') { px(cx, y + 1, 1, 1, color); px(cx, y + 3, 1, 1, color); cx += 2; continue; }
      for (let i = 0; i < 15; i += 1) if (g[i] === '1') px(cx + (i % 3), y + Math.floor(i / 3), 1, 1, color);
      cx += 4;
    }
  };
  return { px, text };
}

// The steak seen from the side: rows of meat whose colour follows the peak
// at each depth, mirrored through the middle for a slab, with fixed marbling,
// rounded corners and a slightly uneven top. `grain` scales the detail.
function drawSteak(px, x, y, w, h, peaks, { crust = 0, marbling, fatCap, grain = 1, bone = 'none' }) {
  const n = peaks.length;
  const r = 2 * grain;
  const wobble = rng(w * 31 + h);
  const dips = Array.from({ length: w }, () => (wobble() > 0.8 ? grain : 0));
  const inside = (col, row) => {
    if (row < dips[col]) return false;
    const dx = Math.max(0, r - col, col - (w - 1 - r));
    const dy = Math.max(0, r - row, row - (h - 1 - r));
    return dx * dx + dy * dy <= r * r;
  };
  const crustColor = crust > 0.6 ? '#4a2c1c' : crust > 0.3 ? '#6b412a' : '#8a5a3c';
  for (let col = 0; col < w; col += 1) {
    const edge = Math.abs((col + 0.5) / w * 2 - 1) ** 6;
    let top = -1;
    let bottom = -1;
    for (let row = 0; row < h; row += 1) {
      if (!inside(col, row)) continue;
      if (top < 0) top = row;
      bottom = row;
      const rho = Math.max(Math.abs((row + 0.5) / h * 2 - 1), edge); // 1 at the faces, 0 in the middle
      px(x + col, y + row, 1, 1, shade(peaks[Math.min(n - 1, Math.round(rho * (n - 1)))]));
    }
    if (crust > 0 && top >= 0) {
      px(x + col, y + top, 1, grain, crustColor);
      px(x + col, y + bottom - grain + 1, 1, grain, crustColor);
    }
  }
  for (const [mx, my] of marbling) {
    const col = mx * grain, row = my * grain;
    if (col < w - r && row < h - r && inside(col, row)) px(x + col, y + row, grain, grain, C.fat);
  }
  if (fatCap) {
    for (let row = r + grain; row < h - r - grain; row += 1) px(x + w - 2 * grain, y + row, 2 * grain, 1, C.fat);
  }
  // A rib crossing the full thickness: about 28 mm of an 180 mm steak, ivory
  // shell around pink marrow, in the middle or along the far edge.
  if (bone !== 'none') {
    const bw = Math.max(3, Math.round(w * 28 / 180));
    const bx = bone === 'middle' ? x + Math.round((w - bw) / 2) : x + r;
    px(bx, y + grain, bw, h - 2 * grain, C.bone);
    if (bw >= 5) px(bx + grain, y + 2 * grain, bw - 2 * grain, h - 4 * grain, C.marrow);
  }
}

export function drawKitchen({ px, text }, frame) {
  const { scene, point, peaks, bathF, t, tick, marbling, fatCap, coreF, targetF, crust, hot, bone = 'none' } = frame;
  // Wall tiles, a shelf with a plant, the counter.
  px(0, 0, W, H, C.wall);
  for (let y = 0; y < 78; y += 8) for (let x = (y / 8) % 2 ? 4 : 0; x < W; x += 8) px(x, y, 4, 4, C.tile);
  px(148, 14, 44, 3, C.edge);
  px(156, 6, 10, 8, C.clay); px(157, 5, 8, 1, C.amber);
  [[160, 0], [158, 2], [163, 1], [161, 3]].forEach(([lx, ly]) => px(lx, ly, 2, 3, C.moss));
  px(170, 9, 4, 5, C.steelDark); px(176, 8, 5, 6, C.mossDark); px(183, 10, 6, 4, C.butter);
  px(0, 78, W, 34, C.counter);
  px(0, 78, W, 2, C.edge);
  for (let y = 86; y < H; y += 8) px(0, y, W, 1, C.plank);

  const sway = Math.round(Math.sin(tick / 300));
  if (scene === 'bath') {
    // Pot of water with a circulator clipped on the side.
    px(12, 36, 66, 44, C.steelDark);
    px(14, 38, 62, 40, C.steel);
    px(16, 44, 58, 34, C.water);
    for (let x = 16; x < 74; x += 1) px(x, 44 + (Math.sin(x / 4 + tick / 250) > 0.6 ? -1 : 0), 1, 1, C.foam);
    px(16, 70, 58, 8, C.waterDeep);
    // The bag: a pale outline around the steak.
    const by = 56 + sway;
    px(23, by - 2, 40, 16, C.foam);
    drawSteak(px, 25, by, 36, 12, peaks, { marbling, fatCap, bone });
    const r = rng(Math.floor(tick / 120));
    for (let i = 0; i < 7; i += 1) {
      const bx = 18 + Math.floor(r() * 54);
      const bubbleY = 76 - ((tick / 40 + i * 9) % 30);
      px(bx, bubbleY, 1, 1, C.foam);
    }
    px(69, 18, 15, 54, C.ink);
    px(70, 22, 13, 9, C.iron);
    text(Math.round(bathF), 71, 24, C.butter);
    px(73, 36, 7, 1, hot ? C.clay : C.moss);
    px(66, 34, 3, 6, C.ink); // the clamp over the pot's rim
    px(74, 66, 4, 6, C.steelDark);
  } else if (scene === 'sear') {
    // Burner, flames, cast iron, steam and spatter.
    px(10, 74, 74, 4, C.ink);
    const r = rng(Math.floor(tick / 90));
    for (let x = 16; x < 78; x += 3) {
      const f = 2 + Math.floor(r() * 4);
      px(x, 74 - f, 2, f, r() > 0.5 ? C.amber : C.butter);
    }
    px(12, 60, 66, 9, C.iron);
    px(12, 60, 66, 1, C.ironHi);
    px(78, 62, 26, 3, C.iron);
    drawSteak(px, 22, 50, 44, 10, peaks, { crust, marbling, fatCap, bone });
    for (let i = 0; i < 5; i += 1) {
      const sy = 46 - ((tick / 30 + i * 8) % 26);
      px(26 + i * 9 + Math.round(Math.sin(sy / 3) * 2), sy, 2, 2, C.paper);
    }
    for (let i = 0; i < 6; i += 1) if (r() > 0.4) px(16 + Math.floor(r() * 60), 56 + Math.floor(r() * 4), 1, 1, C.butter);
  } else {
    // Resting on the board, one lazy wisp.
    px(10, 70, 78, 8, C.board);
    px(10, 76, 78, 2, C.boardDark);
    drawSteak(px, 22, 58, 50, 12, peaks, { crust, marbling, fatCap, bone });
    const wy = 54 - ((tick / 60) % 18);
    px(44 + Math.round(Math.sin(wy / 2) * 2), wy, 1, 2, C.paper);
  }

  // Cross-section card: the steak cut open, edge to edge.
  px(100, 26, 92, 46, C.paper);
  px(100, 26, 92, 1, C.edge); px(100, 71, 92, 1, C.edge);
  drawSteak(px, 106, 38, 80, 26, peaks, { crust, marbling, fatCap, bone, grain: 2 });
  // Thermometer: core against the target notch.
  const lo = 40, hi = 160;
  const level = (f) => Math.max(0, Math.min(1, (f - lo) / (hi - lo)));
  const mercury = coreF > targetF + 3 ? C.clay : C.moss;
  px(104, 28, 6, 6, C.tile); px(105, 27, 4, 8, C.tile);
  px(105, 29, 4, 4, mercury); px(106, 28, 2, 6, mercury);
  px(110, 29, 74, 4, C.tile);
  px(110, 30, Math.round(73 * level(coreF)), 2, mercury);
  px(110 + Math.round(73 * level(targetF)), 28, 1, 6, C.ink);

  // Clock: elapsed time in the cook.
  const minutes = Math.floor(t);
  text(`${Math.floor(minutes / 60)}:${String(minutes % 60).padStart(2, '0')}`, 164, 92, C.paper);

  // The kitchen cat naps through the bath and wakes for the sear.
  const awake = scene !== 'bath';
  const cx = 128, cy = 86 + (awake ? 0 : Math.round(Math.sin(tick / 500)));
  px(cx, cy + 4, 16, 8, C.cat);
  px(cx + 12, cy, 8, 8, C.cat);
  px(cx + 12, cy - 2, 2, 2, C.cat); px(cx + 18, cy - 2, 2, 2, C.cat);
  px(cx - 4, cy + 9, 5, 2, C.catDark);
  if (awake) { px(cx + 14, cy + 3, 1, 2, C.butter); px(cx + 17, cy + 3, 1, 2, C.butter); }
  else {
    px(cx + 14, cy + 4, 2, 1, C.ink); px(cx + 17, cy + 4, 2, 1, C.ink);
    const z = (tick / 700) % 1;
    px(cx + 22, cy - 4 - Math.round(z * 6), 2, 1, C.soft);
  }
  return point;
}

// A shared frame clock: while anything subscribes, requestAnimationFrame
// publishes the time about every FRAME_MS (pixel art gains nothing from 60 fps).
// Nothing runs while no replay is playing.
let frameNow = 0;
function subscribeFrames(onFrame) {
  let raf;
  const loop = (now) => {
    if (now - frameNow >= FRAME_MS) { frameNow = now; onFrame(); }
    raf = requestAnimationFrame(loop);
  };
  raf = requestAnimationFrame(loop);
  return () => cancelAnimationFrame(raf);
}
const still = () => () => {};
const readFrame = () => frameNow;
const noFrame = () => 0;

// Whether el is on screen in a visible tab. Without IntersectionObserver
// (old browsers, tests) it counts as on screen.
function useOnScreen(el) {
  const store = useMemo(() => {
    let onScreen = typeof IntersectionObserver === 'undefined';
    return {
      subscribe(onChange) {
        if (!el || onScreen) return () => {};
        const observer = new IntersectionObserver(([entry]) => { onScreen = entry.isIntersecting; onChange(); }, { threshold: 0.25 });
        observer.observe(el);
        document.addEventListener('visibilitychange', onChange);
        return () => { observer.disconnect(); document.removeEventListener('visibilitychange', onChange); };
      },
      read: () => onScreen && document.visibilityState !== 'hidden',
    };
  }, [el]);
  return useSyncExternalStore(store.subscribe, store.read, () => false);
}

export default function PixelKitchen({ plan, target, sear, cut }) {
  const [canvas, setCanvas] = useState(null);
  const [strategy, setStrategy] = useState('hot_and_pull');
  // Paused at `paused` minutes, or playing since `run.at` (ms) from `run.from` minutes.
  const [paused, setPaused] = useState(0);
  const [run, setRun] = useState(null);
  const [shownPlan, setShownPlan] = useState(plan);
  const trace = plan.trace[strategy];
  const end = trace.at(-1).min;
  const row = plan[strategy];
  const onScreen = useOnScreen(canvas);
  const now = useSyncExternalStore(run ? subscribeFrames : still, readFrame, noFrame);
  const t = run ? Math.min(end, run.from + (Math.max(0, now - run.at) / PLAY_MS) * end) : paused;

  // Adjust state during render rather than in effects: a new plan rewinds, and
  // the replay stops at the end or once it leaves the screen.
  if (plan !== shownPlan) { setShownPlan(plan); setRun(null); setPaused(0); }
  else if (run && (t >= end || !onScreen)) { setRun(null); setPaused(t); }

  const marbling = useMemo(() => {
    const r = rng(cut.id.length * 7919 + cut.mm);
    const count = cut.id.startsWith('ribeye') ? 26 : cut.id === 'strip' ? 14 : 6;
    return Array.from({ length: count }, () => [Math.floor(r() * 40), Math.floor(r() * 13)]);
  }, [cut.id, cut.mm]);

  const point = pointAt(trace, t);
  const scene = sceneAt(trace, t, sear);
  const bathEnd = trace.filter((p) => p.phase === 'bath').at(-1).min;
  const bathC = row.switch_minutes != null && t > row.switch_minutes ? target : row.bath_c;
  const tick = run ? now : 0;
  const fatCap = cut.id.startsWith('ribeye') || cut.id === 'strip';
  const bone = cut.bone ?? 'none';

  // The canvas is outside React, so drawing it is an effect: one frame per
  // render, and renders only happen on a change or a frame tick.
  useEffect(() => {
    const ctx = canvas?.getContext?.('2d');
    if (!ctx) return;
    drawKitchen(painter(ctx), {
      scene, point, t, tick, marbling, fatCap, bone, peaks: peaksAt(trace, t, 24),
      bathF: toF(bathC), coreF: toF(point.core), targetF: toF(target),
      crust: scene === 'bath' ? 0 : Math.min(1, ((t - bathEnd) * 60) / Math.max(sear, 1)),
      hot: bathC > target,
    });
  }, [canvas, scene, point, t, tick, marbling, fatCap, bone, trace, bathC, target, bathEnd, sear]);

  const pick = useCallback((id) => { setStrategy(id); setRun(null); setPaused(0); }, []);
  const toggle = () => {
    if (run) { setRun(null); setPaused(t); return; }
    setRun({ from: t >= end ? 0 : t, at: performance.now() });
  };
  return (
    <section className="sv-section sv-pixel" aria-label="Replay">
      <h2 className="cc-h3">Replay</h2>
      <div className="cc-segmented sv-seg" role="radiogroup" aria-label="Method to replay">
        {STRATEGIES.map((s) => (
          <button key={s.id} type="button" role="radio" className="cc-segmented__item" aria-checked={s.id === strategy}
            onClick={() => pick(s.id)}>{s.name}</button>
        ))}
      </div>
      <canvas ref={setCanvas} width={W} height={H} className="sv-pixel__canvas" role="img"
        aria-label={`${scene === 'bath' ? 'In the bath' : scene === 'sear' ? 'Searing' : 'Resting'} at ${fmtMinutes(t)}, core ${Math.round(toF(point.core))}°F`} />
      <div className="sv-pixel__bar">
        <button type="button" className="cc-button sv-pixel__play" onClick={toggle}>
          {run ? 'Pause' : t >= end ? 'Replay' : 'Play'}
        </button>
        <input className="cc-range" type="range" aria-label="Time" min={0} max={end} step={end / 400} value={t}
          onChange={(e) => { setRun(null); setPaused(Number(e.target.value)); }} />
        <output className="sv-pixel__readout">{fmtMinutes(t)} · {Math.round(toF(point.core))}°F</output>
      </div>
    </section>
  );
}
