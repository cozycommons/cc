import React, { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from 'react';
import { STRATEGIES, Segmented, fmtF, fmtMinutes, shade, sliceEarly, toF } from './SousVideApp.jsx';

// A pixel-art replay of one cook from the plan's trace: the bag in the bath, the
// pan, the board, and a cross-section cut through the steak. The cut is coloured
// by each layer's peak, the colour meat keeps once cooked; beside it, a bar per
// layer shows how hot that layer is right now against the target. Both come from
// the solver's per-layer temperatures (trace points' `layers`, at the plan's
// `layer_rho`). The canvas is drawn at W x H and scaled up with image-rendering:
// pixelated.
export const W = 200;
export const H = 112;
const PLAY_MS = 16000; // a whole cook, any length, replays in this long
const FRAME_MS = 83; // about 12 fps

const C = {
  wall: '#e7dcc5', tile: '#dccfb4', counter: '#694b36', plank: '#5a3f2d', edge: '#8a6448',
  ink: '#3d2f29', soft: '#6f6256', paper: '#f2eadb', butter: '#f0c477', amber: '#d39155',
  clay: '#b76845', moss: '#69755a', mossDark: '#465243', steel: '#9aa3a2', steelDark: '#6e7b7e',
  water: '#8fb3b6', waterDeep: '#6f9599', foam: '#d9ebe8', iron: '#2d2422', ironHi: '#4a3d39',
  board: '#c99b6d', sear: '#8b3a2a', boardDark: '#a77b52', fat: '#f3e4cf', bone: '#efe6d2', marrow: '#c98f7a', cat: '#8a6f5a', catDark: '#5e4a3c',
};

// 3x5 digits for the circulator and the clock.
const GLYPHS = {
  0: '111101101101111', 1: '010110010010111', 2: '111001111100111', 3: '111001111001111',
  4: '101101111001001', 5: '111100111001111', 6: '111100111101111', 7: '111001001001001',
  8: '111101111101111', 9: '111101111001111', F: '111100110100100', ':': '0',
};

// Temperature at fractional radius rho (0 centre, 1 surface): linear between the
// solver's layers at `rhos` when the point has them, otherwise between the core,
// middle (about half way out) and surface readings.
export function tempAt(point, rho, rhos) {
  const { layers } = point;
  if (!layers || !rhos) {
    return rho <= 0.5
      ? point.core + (point.mid - point.core) * (rho / 0.5)
      : point.mid + (point.surface - point.mid) * ((rho - 0.5) / 0.5);
  }
  let i = 1;
  while (i < rhos.length - 1 && rhos[i] < rho) i += 1;
  const f = Math.max(0, Math.min(1, (rho - rhos[i - 1]) / (rhos[i] - rhos[i - 1])));
  return layers[i - 1] + (layers[i] - layers[i - 1]) * f;
}

// The trace point at minute t, linearly between readings.
export function pointAt(trace, t) {
  if (t <= trace[0].min) return trace[0];
  for (let i = 1; i < trace.length; i += 1) {
    const a = trace[i - 1];
    const b = trace[i];
    if (t <= b.min) {
      const f = (t - a.min) / (b.min - a.min || 1);
      const mix = (x, y) => x + (y - x) * f;
      const out = { min: t, phase: b.phase, core: mix(a.core, b.core), mid: mix(a.mid, b.mid), surface: mix(a.surface, b.surface) };
      if (a.layers && b.layers) out.layers = a.layers.map((x, k) => mix(x, b.layers[k]));
      return out;
    }
  }
  return trace.at(-1);
}

// Temperature at each of n radii, centre first.
export const liveAt = (point, n, rhos) => Array.from({ length: n }, (_, i) => tempAt(point, i / (n - 1), rhos));

// Peak temperature so far at each of n radii, centre first.
export function peaksAt(trace, t, n, rhos) {
  const peaks = Array(n).fill(-Infinity);
  const visit = (p) => { for (let i = 0; i < n; i += 1) peaks[i] = Math.max(peaks[i], tempAt(p, i / (n - 1), rhos)); };
  for (const p of trace) { if (p.min > t) break; visit(p); }
  visit(pointAt(trace, t));
  return peaks;
}

// Shares of the replay for the bath and the sear; the rest gets what is left. A
// 45 s sear is under 1 % of a cook, so at its true pace it would flash past in a
// frame; the replay (and its slider) slows down for the sear and the rest.
const SHARES = { bath: 0.55, sear: 0.15 };

// The replay's timeline: [fraction of the replay, cook minute] knots at the
// bath's start, its end, the sear's end and the rest's end.
export function timeline(trace, searS) {
  const bathEnd = trace.filter((p) => p.phase === 'bath').at(-1).min;
  const end = trace.at(-1).min;
  const searEnd = Math.min(end, bathEnd + searS / 60);
  const sear = searEnd > bathEnd ? SHARES.sear : 0;
  const bath = end > searEnd ? SHARES.bath : 1 - sear;
  return [[0, 0], [bath, bathEnd], [bath + sear, searEnd], [1, end]];
}

// The cook minute at replay fraction f.
export function minuteAt(knots, f) {
  for (let i = 1; i < knots.length; i += 1) {
    const [fa, ta] = knots[i - 1];
    const [fb, tb] = knots[i];
    if (f <= fb && fb > fa) return ta + (tb - ta) * Math.max(0, (f - fa) / (fb - fa));
  }
  return knots.at(-1)[1];
}

// Where the cook is at minute t: in the bath, searing, or resting.
export function sceneAt(trace, t, searS) {
  const bathEnd = trace.filter((p) => p.phase === 'bath').at(-1)?.min ?? 0;
  if (t <= bathEnd) return 'bath';
  return t - bathEnd <= searS / 60 ? 'sear' : 'rest';
}

// What is happening at minute t, in a first-time cook's words. `row` is the
// method's plan row, `bathC` the bath right now, `next` the point a little later
// (to tell a climbing center from a falling one).
export function storyAt({ trace, t, scene, row, target, sear, bathC, point, next }) {
  const core = fmtF(point.core);
  if (scene === 'bath') {
    if (t <= 0) return `Into the ${fmtF(bathC)} bath straight from the fridge, ${core} all the way through.`;
    if (row.switch_minutes != null && t > row.switch_minutes) {
      return `The bath is down to ${fmtF(target)}, so the outside stops climbing while the center catches up: ${core}.`;
    }
    const bathEnd = trace.filter((p) => p.phase === 'bath').at(-1).min;
    if (t >= bathEnd * 0.9) {
      return row.bath_c > target
        ? `Nearly time to pull it at ${core}. The sear and rest carry the center the last few degrees.`
        : `The center has nearly caught up with the bath: ${core}.`;
    }
    return `Heat creeps in from the outside. The edge is ${fmtF(point.surface)}, the center ${core}.`;
  }
  if (scene === 'sear') {
    const bathEnd = trace.filter((p) => p.phase === 'bath').at(-1).min;
    const hottest = Math.max(point.surface, ...trace.filter((p) => p.min > bathEnd && p.min <= bathEnd + sear / 60 + 1e-6).map((p) => p.surface));
    // The key under the canvas shows the surface now, so the caption names it too.
    const now = fmtF(point.surface);
    const peak = fmtF(hottest) === now ? '' : `, ${fmtF(hottest)} by the end of the sear`;
    return `Searing: the surface is ${now}${peak}, but only a thin layer gets that hot. The center, ${core}, hasn't felt it yet.`;
  }
  const climbing = next.core > point.core + 0.02;
  const peak = trace.filter((p) => p.phase === 'finish').reduce((a, b) => (b.core > a.core ? b : a));
  if (!climbing) return `Rested: the center topped out at ${fmtF(peak.core)} and the crust has cooled to ${fmtF(point.surface)}. Slice it.`;
  const early = sliceEarly(trace, sear);
  const rested = t - trace.filter((p) => p.phase === 'bath').at(-1).min - sear / 60;
  if (early && rested >= early.min) {
    return `Cut now and the center is ${core}. Wait and it reaches ${fmtF(peak.core)}, but the crust cools to ${fmtF(early.crust)}.`;
  }
  return `Resting: heat under the crust keeps moving in, so the center is still climbing (${core}) while the crust cools (${fmtF(point.surface)}).`;
}

// The colour of a layer's bar: cool below the target, butter at it, clay past it.
export function barColor(c, targetC) {
  if (c < targetC - 2) return C.water;
  if (c <= targetC + 2) return C.butter;
  return c > targetC + BAR_OVER_C ? C.sear : C.clay;
}
// The bars' scale: from BAR_UNDER_C below the target, where the bath starts
// to show, to BAR_OVER_C past it, where only the sear reaches.
const BAR_UNDER_C = 20;
const BAR_OVER_C = 10;

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
  const { live = peaks, crustF = coreF, targetC = ((targetF - 32) * 5) / 9, done = false } = frame;
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

  // Cross-section card: the steak cut open, edge to edge, coloured by each
  // layer's peak, and beside it a bar per row for how hot that layer is now.
  px(100, 24, 92, 48, C.paper);
  px(100, 24, 92, 1, C.edge); px(100, 71, 92, 1, C.edge);
  const sy = 40, sh = 26;
  drawSteak(px, 104, sy, 56, sh, peaks, { crust, marbling, fatCap, bone, grain: 2 });
  const bx = 164, bw = 24, n = live.length;
  const barX = (c) => Math.round(bw * Math.max(0, Math.min(1, (c - targetC + BAR_UNDER_C) / (BAR_UNDER_C + BAR_OVER_C))));
  px(bx, sy, bw, sh, C.tile);
  for (let row = 0; row < sh; row += 1) {
    const c = live[Math.min(n - 1, Math.round(Math.abs((row + 0.5) / sh * 2 - 1) * (n - 1)))];
    px(bx, sy + row, barX(c), 1, barColor(c, targetC));
  }
  for (let y = sy - 1; y < sy + sh + 1; y += 2) px(bx + barX(targetC), y, 1, 1, C.ink); // the target
  // Thermometers: the center against the target notch, and the crust.
  const lo = 40, hi = 160;
  const level = (f) => Math.max(0, Math.min(1, (f - lo) / (hi - lo)));
  const gauge = (y, f, color) => {
    px(104, y + 1, 4, 3, C.tile); px(105, y, 2, 5, C.tile);
    px(105, y + 1, 2, 3, color);
    px(109, y + 1, 79, 3, C.tile);
    px(109, y + 2, Math.round(78 * level(f)), 1, color);
  };
  gauge(27, coreF, coreF > targetF + 3 ? C.clay : C.moss);
  gauge(33, crustF, '#6b412a');
  px(109 + Math.round(78 * level(targetF)), 27, 1, 5, C.ink);

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
  if (awake) {
    // Eyes on the pan while it sizzles, then on the board; a heart once it's ready.
    const look = scene === 'sear' ? 0 : -1;
    px(cx + 14 + look, cy + 3, 1, 2, C.butter); px(cx + 17 + look, cy + 3, 1, 2, C.butter);
    if (done) {
      const hy = cy - 7 - Math.round(Math.sin(tick / 400));
      px(cx + 20, hy, 2, 1, C.clay); px(cx + 23, hy, 2, 1, C.clay); px(cx + 20, hy + 1, 5, 1, C.clay); px(cx + 21, hy + 2, 3, 1, C.clay); px(cx + 22, hy + 3, 1, 1, C.clay);
    }
  }
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
  // Paused at fraction `paused` of the replay, or playing since `run.at` (ms) from fraction `run.from`.
  const [paused, setPaused] = useState(0);
  const [run, setRun] = useState(null);
  const [shownPlan, setShownPlan] = useState(plan);
  const trace = plan.trace[strategy];
  const end = trace.at(-1).min;
  const row = plan[strategy];
  const knots = timeline(trace, sear);
  const onScreen = useOnScreen(canvas);
  const now = useSyncExternalStore(run ? subscribeFrames : still, readFrame, noFrame);
  const f = run ? Math.min(1, run.from + Math.max(0, now - run.at) / PLAY_MS) : paused;
  const t = minuteAt(knots, f);

  // Adjust state during render rather than in effects: a new plan rewinds, and
  // the replay stops at the end or once it leaves the screen.
  if (plan !== shownPlan) { setShownPlan(plan); setRun(null); setPaused(0); }
  else if (run && (f >= 1 || !onScreen)) { setRun(null); setPaused(f); }

  const marbling = useMemo(() => {
    const r = rng(cut.id.length * 7919 + cut.mm);
    const count = cut.id.startsWith('ribeye') ? 26 : cut.id === 'strip' ? 14 : 6;
    return Array.from({ length: count }, () => [Math.floor(r() * 40), Math.floor(r() * 13)]);
  }, [cut.id, cut.mm]);

  const rhos = plan.layer_rho;
  const point = pointAt(trace, t);
  const next = pointAt(trace, Math.min(end, t + 0.5));
  const scene = sceneAt(trace, t, sear);
  const bathEnd = trace.filter((p) => p.phase === 'bath').at(-1).min;
  const bathC = row.switch_minutes != null && t > row.switch_minutes ? target : row.bath_c;
  const tick = run ? now : 0;
  const fatCap = cut.id.startsWith('ribeye') || cut.id === 'strip';
  const bone = cut.bone ?? 'none';
  const story = storyAt({ trace, t, scene, row, target, sear, bathC, point, next });
  const done = scene === 'rest' && next.core <= point.core + 0.02;

  // The canvas is outside React, so drawing it is an effect: one frame per
  // render, and renders only happen on a change or a frame tick.
  useEffect(() => {
    const ctx = canvas?.getContext?.('2d');
    if (!ctx) return;
    drawKitchen(painter(ctx), {
      scene, point, t, tick, marbling, fatCap, bone, done, peaks: peaksAt(trace, t, 24, rhos), live: liveAt(point, 24, rhos),
      bathF: toF(bathC), coreF: toF(point.core), crustF: toF(point.surface), targetF: toF(target), targetC: target,
      crust: scene === 'bath' ? 0 : Math.min(1, ((t - bathEnd) * 60) / Math.max(sear, 1)),
      hot: bathC > target,
    });
  }, [canvas, scene, point, t, tick, marbling, fatCap, bone, done, trace, rhos, bathC, target, bathEnd, sear]);

  const pick = useCallback((id) => { setStrategy(id); setRun(null); setPaused(0); }, []);
  const toggle = () => {
    if (run) { setRun(null); setPaused(f); return; }
    setRun({ from: f >= 1 ? 0 : f, at: performance.now() });
  };
  return (
    <section className="sv-section sv-pixel" aria-label="Replay">
      <h2 className="cc-h3">Replay</h2>
      <Segmented label="Method to replay" showLabel={false} items={STRATEGIES.map((s) => ({ key: s.id, name: s.name }))}
        value={strategy} onChange={pick} />
      <canvas ref={setCanvas} width={W} height={H} className="sv-pixel__canvas" role="img"
        aria-label={`${scene === 'bath' ? 'In the bath' : scene === 'sear' ? 'Searing' : 'Resting'} at ${fmtMinutes(t)}, center ${fmtF(point.core)}, crust ${fmtF(point.surface)}`} />
      <p className="sv-pixel__story">{story}</p>
      <div className="sv-pixel__bar">
        <button type="button" className="cc-button sv-pixel__play" onClick={toggle}>
          {run ? 'Pause' : f >= 1 ? 'Replay' : 'Play'}
        </button>
        <input className="cc-range" type="range" aria-label="Time" aria-valuetext={fmtMinutes(t)} min={0} max={1} step={0.0025} value={f}
          onChange={(e) => { setRun(null); setPaused(Number(e.target.value)); }} />
        <output className="sv-pixel__readout">{fmtMinutes(t)}</output>
      </div>
      <p className="sv-pixel__key">
        <span><i className="sv-pixel__swatch sv-pixel__swatch--center" />Center {fmtF(point.core)}</span>
        <span><i className="sv-pixel__swatch sv-pixel__swatch--crust" />Crust {fmtF(point.surface)}</span>
        <span>The cut shows the color each layer has cooked to; the bars beside it, how hot each layer is now, with the dotted line at your target.</span>
      </p>
    </section>
  );
}
