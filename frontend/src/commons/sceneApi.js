import { resolveRuntimeServiceUrl } from '../runtimeConfig.js';
import { DICE_SAME_ORIGIN } from '../../sandboxConstants.js';

const CLIENT_ID_KEY = 'cozy-commons.scene-client-id';
const PENDING_COMMAND_KEY = 'cozy-commons.pending-command';

function apiPath(path) {
  const configured = import.meta.env.VITE_API_URL;
  const base = resolveRuntimeServiceUrl(configured);
  if (!base) throw new Error('VITE_API_URL is missing');
  return configured === DICE_SAME_ORIGIN ? `/api${path}` : `${base}${path}`;
}

function newClientId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `browser-${Date.now()}-${Math.random().toString(36).slice(2)}`;
}

export function getSceneClientId() {
  try {
    const existing = window.localStorage.getItem(CLIENT_ID_KEY);
    if (existing) return existing;
    const created = newClientId();
    window.localStorage.setItem(CLIENT_ID_KEY, created);
    return created;
  } catch {
    return newClientId();
  }
}

export function savePendingSceneCommand(command) {
  try {
    window.localStorage.setItem(PENDING_COMMAND_KEY, JSON.stringify(command));
  } catch {
    // The request still works when storage is unavailable; it just cannot be
    // retried automatically after the page is closed.
  }
}

export function getPendingSceneCommand() {
  try {
    const value = window.localStorage.getItem(PENDING_COMMAND_KEY);
    return value ? JSON.parse(value) : null;
  } catch {
    return null;
  }
}

export function clearPendingSceneCommand(commandId) {
  try {
    const value = getPendingSceneCommand();
    if (!commandId || value?.client_command_id === commandId) {
      window.localStorage.removeItem(PENDING_COMMAND_KEY);
    }
  } catch {
    // Ignore storage failures; the server remains authoritative.
  }
}

async function request(path, options = {}) {
  const startedAtWallMs = Date.now();
  const startedAtMonoMs = globalThis.performance?.now?.() ?? startedAtWallMs;
  const response = await fetch(apiPath(path), {
    cache: 'no-store',
    ...options,
    headers: {
      Accept: 'application/json',
      ...(options.body ? { 'Content-Type': 'application/json' } : {}),
      ...(options.headers || {}),
    },
  });
  const body = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = body?.detail;
    const error = new Error(detail?.message || detail?.code || `Commons API failed: ${response.status}`);
    error.status = response.status;
    error.code = detail?.code;
    error.currentVersion = detail?.current_version;
    throw error;
  }
  if (body && typeof body === 'object' && Number.isFinite(Number(body.server_time_ms))) {
    const finishedAtMonoMs = globalThis.performance?.now?.() ?? Date.now();
    const roundTripMs = Math.max(0, finishedAtMonoMs - startedAtMonoMs);
    try {
      Object.defineProperty(body, '__client_timing', {
        configurable: true,
        enumerable: false,
        value: Object.freeze({
          midpoint_ms: startedAtWallMs + roundTripMs / 2,
          uncertainty_ms: roundTripMs / 2,
        }),
      });
    } catch {
      // A frozen response can still be rendered using the receipt-time clock.
    }
  }
  return body;
}

export function getScene() {
  return request('/commons/scene');
}

export function sendSceneCommand(command, clientId = getSceneClientId()) {
  return request('/commons/scene/commands', {
    method: 'POST',
    headers: { 'X-Scene-Client-Id': clientId },
    body: JSON.stringify(command),
  });
}
