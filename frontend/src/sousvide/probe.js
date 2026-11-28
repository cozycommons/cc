// A live thermometer for a running cook, from one of two places:
// - a Bluetooth probe the page talks to itself (Web Bluetooth: Chrome on Android or
//   a laptop; not iPhone Safari), speaking iBBQ, the protocol of Inkbird's IBT-2X,
//   IBT-4XS and IBT-6XS and many rebadged probes;
// - a home bridge (backend/sousvide/bridge.py, self-hosted), which streams whatever
//   the home network posts to it.
// It is an external store for useSyncExternalStore. Readings arrive as events
// (Bluetooth notifications, server-sent events), so nothing here polls or ticks.
import { getUrl } from '../api.js';

const IBBQ = 0xfff0;
const LIVE = 0xfff4; // notifies each probe's temperature, about once a second
const LOGIN = 0xfff2;
const SETTINGS = 0xfff5;
// The fixed pairing bytes every iBBQ probe expects before it will report.
const LOGIN_KEY = new Uint8Array([0x21, 0x07, 0x06, 0x05, 0x04, 0x03, 0x02, 0x01, 0xb8, 0x22, 0, 0, 0, 0, 0]);
const REALTIME_ON = new Uint8Array([0x0b, 0x01, 0, 0, 0, 0]);
const NO_PROBE = 0xfff6;

// One iBBQ notification: a little-endian uint16 per probe socket, in tenths of a
// degree Celsius, or NO_PROBE for an empty socket.
export function probeTemps(view) {
  const out = [];
  for (let i = 0; i + 1 < view.byteLength; i += 2) {
    const raw = view.getUint16(i, true);
    out.push(raw === NO_PROBE ? null : raw / 10);
  }
  return out;
}

export const canBluetooth = () => typeof navigator !== 'undefined' && Boolean(navigator.bluetooth);
// The self-host server marks the page it serves (selfhost.BRIDGE_META).
export const bridgeHere = () => typeof document !== 'undefined'
  && Boolean(document.querySelector('meta[name="sousvide-bridge"]'));

// status: off, connecting, live (f is the reading), lost (it will say when it is back), error.
const OFF = { status: 'off', source: null, f: null, message: null };
let state = OFF;
const listeners = new Set();
const set = (next) => { state = { ...state, ...next }; listeners.forEach((l) => l()); };
export const subscribeProbe = (l) => { listeners.add(l); return () => listeners.delete(l); };
export const readProbe = () => state;
export const offProbe = () => OFF;

// The running connection: what disconnect() undoes.
let link = null;

// What the cook passes on connect: the °F that means "take it out" (one alarm, once)
// and where each reading goes.
function onReading(f, { pullF, onTemp }) {
  set({ status: 'live', f, message: null });
  onTemp(f);
  if (link && !link.rang && f >= pullF) {
    link.rang = true;
    ring(link.audio);
  }
}

// Three short beeps and a buzz. The sound is scheduled on the audio clock in one
// go; the context was made on the tap that connected, so the browser lets it play.
function ring(audio) {
  navigator.vibrate?.([400, 200, 400, 200, 400]);
  if (!audio) return;
  const t = audio.currentTime;
  [0, 0.35, 0.7].forEach((at) => {
    const osc = audio.createOscillator();
    const gain = audio.createGain();
    osc.frequency.value = 880;
    gain.gain.setValueAtTime(0.25, t + at);
    gain.gain.setValueAtTime(0, t + at + 0.2);
    osc.connect(gain).connect(audio.destination);
    osc.start(t + at);
    osc.stop(t + at + 0.2);
  });
}

// Keeps the screen on while a probe is connected: a phone that sleeps drops
// Bluetooth and the page with it. The lock is let go when the page hides, so it is
// asked for again when the page comes back.
async function holdScreen(mine) {
  try {
    const wake = await navigator.wakeLock?.request('screen');
    if (link === mine) mine.wake = wake;
    else wake?.release();
  } catch { /* not allowed or not supported */ }
}
function onVisible() {
  if (document.visibilityState === 'visible' && link) holdScreen(link);
}

function begin(source, cook) {
  disconnect();
  const Audio = typeof window !== 'undefined' && (window.AudioContext || window.webkitAudioContext);
  link = { source, cook, rang: false, audio: Audio ? new Audio() : null, close: () => {} };
  document.addEventListener('visibilitychange', onVisible);
  holdScreen(link);
  set({ status: 'connecting', source, f: null, message: null });
  return link;
}

// The Bluetooth chooser needs the tap itself, so call this from a click.
export async function connectBluetooth(cook) {
  const mine = begin('bluetooth', cook);
  try {
    const device = await navigator.bluetooth.requestDevice({
      filters: [{ namePrefix: 'iBBQ' }, { services: [IBBQ] }], optionalServices: [IBBQ],
    });
    mine.device = device;
    device.addEventListener('gattserverdisconnected', () => {
      if (link === mine) set({ status: 'lost', message: 'The thermometer dropped. Bring the phone closer and reconnect.' });
    });
    await listen(mine);
  } catch (error) {
    if (link === mine) fail(error);
  }
}

// After a drop: the same probe, no chooser.
export async function reconnectBluetooth() {
  const mine = link;
  if (!mine?.device) return;
  set({ status: 'connecting', message: null });
  try { await listen(mine); } catch (error) { if (link === mine) fail(error); }
}

async function listen(mine) {
  const server = await mine.device.gatt.connect();
  const service = await server.getPrimaryService(IBBQ);
  await (await service.getCharacteristic(LOGIN)).writeValue(LOGIN_KEY);
  const live = await service.getCharacteristic(LIVE);
  const onFrame = (event) => {
    // The first probe plugged in is the steak's.
    const c = probeTemps(event.target.value).find((t) => t != null);
    if (c != null && link === mine) onReading(Math.round((c * 9 / 5 + 32) * 10) / 10, mine.cook);
  };
  live.addEventListener('characteristicvaluechanged', onFrame);
  await live.startNotifications();
  await (await service.getCharacteristic(SETTINGS)).writeValue(REALTIME_ON);
  mine.close = () => {
    live.removeEventListener('characteristicvaluechanged', onFrame);
    if (mine.device.gatt.connected) mine.device.gatt.disconnect();
  };
}

// The home bridge's stream. EventSource reconnects by itself after a drop.
export function connectBridge(cook) {
  const mine = begin('bridge', cook);
  const events = new EventSource(`${getUrl()}/sousvide/probe/stream`);
  events.onmessage = (event) => {
    const { f } = JSON.parse(event.data);
    if (link === mine && Number.isFinite(f)) onReading(f, cook);
  };
  events.onerror = () => {
    if (link === mine) set({ status: 'lost', message: 'Lost the home bridge. Trying again…' });
  };
  mine.close = () => events.close();
}

function fail(error) {
  // Closing the chooser is a choice, not an error.
  const cancelled = error?.name === 'NotFoundError';
  disconnect();
  if (!cancelled) set({ status: 'error', message: error?.message || 'Could not connect to the thermometer.' });
}

export function disconnect() {
  if (!link) return;
  const old = link;
  link = null;
  document.removeEventListener('visibilitychange', onVisible);
  old.close();
  old.wake?.release?.().catch?.(() => {});
  old.audio?.close?.().catch?.(() => {});
  set(OFF);
}
