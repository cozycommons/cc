const STORAGE_KEY = 'dice.live-command-latency.v1';
const SAMPLE_TTL_MS = 7 * 24 * 60 * 60 * 1000;

export const COMMAND_HEDGE_COLD_START_MS = 1200;
export const COMMAND_HEDGE_MIN_MS = 750;
export const COMMAND_HEDGE_MAX_MS = 2500;
export const COMMAND_HEDGE_SAMPLE_LIMIT = 20;
export const COMMAND_HEDGE_MIN_SAMPLES = 5;

const clamp = (value, minimum, maximum) => Math.min(maximum, Math.max(minimum, value));

const browserStorage = () => {
  try { return globalThis.localStorage; } catch { return null; }
};

export function readCommandLatencySamples(storage = browserStorage(), wallNow = Date.now()) {
  if (!storage) return [];
  try {
    const value = JSON.parse(storage.getItem(STORAGE_KEY) || '{}');
    if (value.version !== 1 || !Array.isArray(value.samples)) return [];
    return value.samples
      .filter((sample) => Number.isFinite(sample?.latency_ms)
        && sample.latency_ms >= 0
        && Number.isFinite(sample?.recorded_at)
        && wallNow - sample.recorded_at <= SAMPLE_TTL_MS)
      .slice(-COMMAND_HEDGE_SAMPLE_LIMIT);
  } catch {
    return [];
  }
}

export function recordCommandLatency(storage, latencyMs, wallNow = Date.now()) {
  if (!storage || !Number.isFinite(latencyMs) || latencyMs < 0) return;
  const samples = readCommandLatencySamples(storage, wallNow);
  samples.push({ latency_ms: Math.round(latencyMs), recorded_at: wallNow });
  try {
    storage.setItem(STORAGE_KEY, JSON.stringify({
      version: 1,
      samples: samples.slice(-COMMAND_HEDGE_SAMPLE_LIMIT),
    }));
  } catch {
    // Latency learning must never block referee input.
  }
}

export function commandHedgeDelay(samples) {
  if (!Array.isArray(samples) || samples.length < COMMAND_HEDGE_MIN_SAMPLES) {
    return COMMAND_HEDGE_COLD_START_MS;
  }
  const ordered = samples.map((sample) => sample.latency_ms).sort((left, right) => left - right);
  const p90Index = Math.max(0, Math.ceil(ordered.length * 0.9) - 1);
  return clamp(ordered[p90Index], COMMAND_HEDGE_MIN_MS, COMMAND_HEDGE_MAX_MS);
}

const defaultNow = () => globalThis.performance?.now?.() ?? Date.now();

export function sendLiveCommandWithAdaptiveHedge(request, {
  storage = browserStorage(),
  now = defaultNow,
  wallNow = Date.now,
  setTimer = globalThis.setTimeout,
  clearTimer = globalThis.clearTimeout,
  onTelemetry = () => {},
} = {}) {
  const hedgeDelayMs = commandHedgeDelay(readCommandLatencySamples(storage, wallNow()));
  const startedAt = now();
  const originalController = new AbortController();
  let hedgeController = null;
  let hedgeTimer = null;
  let hedgeStarted = false;
  let hedgeTriggeredByDelay = false;
  let settled = false;
  let originalObserved = false;
  let pendingAttempts = 0;

  const observeOriginal = (latencyMs) => {
    if (originalObserved) return;
    originalObserved = true;
    recordCommandLatency(storage, latencyMs, wallNow());
  };

  return new Promise((resolve, reject) => {
    const finish = (winner, outcome, value) => {
      if (settled) return;
      settled = true;
      if (hedgeTimer !== null) clearTimer(hedgeTimer);

      const loser = winner === 'original' ? hedgeController : originalController;
      const loserCancelled = Boolean(pendingAttempts > 0 && loser && !loser.signal.aborted);
      if (winner === 'hedge' && hedgeTriggeredByDelay) {
        observeOriginal(Math.max(hedgeDelayMs, now() - startedAt));
      }
      if (loserCancelled) loser.abort();

      try {
        onTelemetry({
          attempts: hedgeStarted ? 2 : 1,
          winner,
          duration_ms: Math.round(now() - startedAt),
          hedge_delay_ms: hedgeDelayMs,
          outcome,
          status: outcome === 'rejected' ? value?.status || 0 : 200,
          loser_cancelled: loserCancelled,
        });
      } catch {
        // Diagnostics must never change the command outcome.
      }
      if (outcome === 'resolved') resolve(value);
      else reject(value);
    };

    const startSecondAttempt = (triggeredByDelay) => {
      if (settled || hedgeStarted) return;
      if (hedgeTimer !== null) clearTimer(hedgeTimer);
      hedgeStarted = true;
      hedgeTriggeredByDelay = triggeredByDelay;
      hedgeController = new AbortController();
      launch(triggeredByDelay ? 'hedge' : 'retry', hedgeController);
    };

    const launch = (attempt, controller) => {
      pendingAttempts += 1;
      Promise.resolve()
        .then(() => request({ attempt, signal: controller.signal }))
        .then((value) => {
          pendingAttempts -= 1;
          if (attempt === 'original') observeOriginal(now() - startedAt);
          finish(attempt, 'resolved', value);
        }, (error) => {
          pendingAttempts -= 1;
          if (settled) return;
          const status = Number(error?.status) || 0;
          if (status >= 400 && status < 500) {
            finish(attempt, 'rejected', error);
          } else if (!hedgeStarted) {
            startSecondAttempt(false);
          } else if (pendingAttempts === 0) {
            finish(attempt, 'rejected', error);
          }
        });
    };

    launch('original', originalController);
    hedgeTimer = setTimer(() => {
      startSecondAttempt(true);
    }, hedgeDelayMs);
  });
}
