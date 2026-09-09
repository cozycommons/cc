const DEFAULT_SLEW_MS = 2_000;

function wallNow() {
  return Date.now();
}

function monotonicNow() {
  return globalThis.performance?.now?.() ?? Date.now();
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

/**
 * Keep the server phase continuous between response samples. The injected
 * clocks make correction behavior deterministic in unit and browser fixtures.
 */
export function createPresentationClock({ nowWall = wallNow, nowMono = monotonicNow, slewMs = DEFAULT_SLEW_MS } = {}) {
  let anchorMono = null;
  let anchorServer = null;
  let correction = null;

  function read(atMono = nowMono()) {
    if (!Number.isFinite(anchorMono) || !Number.isFinite(anchorServer)) return nowWall();
    const base = anchorServer + (atMono - anchorMono);
    if (!correction) return base;
    const progress = clamp((atMono - correction.startedAt) / correction.duration, 0, 1);
    const corrected = base + correction.amount * progress;
    if (progress >= 1) {
      anchorServer = corrected;
      anchorMono = atMono;
      correction = null;
    }
    return corrected;
  }

  function observe({ serverTimeMs, midpointMs = nowWall(), uncertaintyMs = Infinity } = {}) {
    if (!Number.isFinite(serverTimeMs) || !Number.isFinite(midpointMs)) return false;
    const sampledAtMono = nowMono();
    const sampledServerNow = serverTimeMs + (nowWall() - midpointMs);
    if (!Number.isFinite(anchorMono) || !Number.isFinite(anchorServer)) {
      anchorMono = sampledAtMono;
      anchorServer = sampledServerNow;
      correction = null;
      return true;
    }
    const current = read(sampledAtMono);
    const amount = sampledServerNow - current;
    if (Math.abs(amount) < 0.5) return true;
    correction = {
      startedAt: sampledAtMono,
      amount,
      duration: Math.max(1, slewMs),
    };
    return true;
  }

  return Object.freeze({
    now: () => read(),
    observe,
    reset: () => {
      anchorMono = null;
      anchorServer = null;
      correction = null;
    },
  });
}
