const DEFAULT_SLEW_MS = 2_000;
const MAX_SLEW_CORRECTION_MS = 100;
const MAX_SAMPLE_UNCERTAINTY_MS = 500;

function wallNow() {
  return Date.now();
}

function monotonicNow() {
  return globalThis.performance?.now?.() ?? Date.now();
}

function clamp(value, minimum, maximum) {
  return Math.min(maximum, Math.max(minimum, value));
}

function finiteNonNegative(value) {
  return Number.isFinite(value) && value >= 0;
}

/**
 * Keep the server phase continuous between response samples. The injected
 * clocks make correction behavior deterministic in unit and browser fixtures.
 */
export function createPresentationClock({ nowWall = wallNow, nowMono = monotonicNow, slewMs = DEFAULT_SLEW_MS } = {}) {
  let anchorMono = null;
  let anchorServer = null;
  let correction = null;
  let pendingCorrection = null;

  function setAnchor(atMono, serverTime) {
    anchorMono = atMono;
    anchorServer = serverTime;
  }

  function read(atMono = nowMono()) {
    if (!Number.isFinite(anchorMono) || !Number.isFinite(anchorServer)) return nowWall();
    const base = anchorServer + (atMono - anchorMono);
    if (!correction) return base;
    const progress = clamp((atMono - correction.startedAt) / correction.duration, 0, 1);
    const corrected = base + correction.amount * progress;
    if (progress >= 1) {
      setAnchor(atMono, corrected);
      correction = null;
    }
    return corrected;
  }

  function observe({ serverTimeMs, midpointMs = nowWall(), uncertaintyMs = Infinity } = {}) {
    if (
      !Number.isFinite(serverTimeMs)
      || !Number.isFinite(midpointMs)
      || !finiteNonNegative(uncertaintyMs)
      || uncertaintyMs > MAX_SAMPLE_UNCERTAINTY_MS
    ) return false;
    const sampledAtMono = nowMono();
    const sampledServerNow = serverTimeMs + (nowWall() - midpointMs);
    if (!Number.isFinite(sampledAtMono) || !Number.isFinite(sampledServerNow)) return false;
    if (!Number.isFinite(anchorMono) || !Number.isFinite(anchorServer)) {
      setAnchor(sampledAtMono, sampledServerNow);
      correction = null;
      pendingCorrection = null;
      return true;
    }
    const current = read(sampledAtMono);
    const amount = sampledServerNow - current;
    if (!Number.isFinite(amount)) return false;

    // A new sample supersedes any prior pending reanchor. Small samples can
    // resume the normal slew path, while large samples remain explicit for
    // the renderer to apply at a safe visual boundary.
    pendingCorrection = null;
    if (Math.abs(amount) > MAX_SLEW_CORRECTION_MS) {
      // Stop an in-progress slew at its current value before waiting for an
      // explicit reanchor. This keeps observe itself continuous.
      setAnchor(sampledAtMono, current);
      correction = null;
      pendingCorrection = Object.freeze({
        amountMs: amount,
        targetServerMs: sampledServerNow,
        sampledAtMonoMs: sampledAtMono,
        uncertaintyMs,
      });
      return true;
    }

    if (Math.abs(amount) < 0.5) {
      setAnchor(sampledAtMono, current);
      correction = null;
      return true;
    }

    // Rebase the linear correction at the value already presented. Without
    // this anchor reset, replacing a mid-slew correction restarts its delta
    // against the old base and causes a visible jump.
    setAnchor(sampledAtMono, current);
    correction = {
      startedAt: sampledAtMono,
      amount,
      // Keep even a caller-supplied short duration monotonic for a negative
      // correction. The default remains the specified two-second slew.
      duration: Math.max(1, slewMs, Math.abs(amount)),
    };
    return true;
  }

  function getPendingCorrection() {
    return pendingCorrection;
  }

  function reanchor() {
    if (!pendingCorrection) return false;
    const atMono = nowMono();
    if (!Number.isFinite(atMono)) return false;
    const elapsed = atMono - pendingCorrection.sampledAtMonoMs;
    setAnchor(atMono, pendingCorrection.targetServerMs + elapsed);
    correction = null;
    pendingCorrection = null;
    return true;
  }

  return Object.freeze({
    now: () => read(),
    observe,
    getPendingCorrection,
    reanchor,
    reset: () => {
      anchorMono = null;
      anchorServer = null;
      correction = null;
      pendingCorrection = null;
    },
  });
}
