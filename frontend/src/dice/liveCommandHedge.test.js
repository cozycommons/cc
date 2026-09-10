import { afterEach, describe, expect, it, vi } from 'vitest';
import {
  COMMAND_HEDGE_SAMPLE_LIMIT,
  commandHedgeDelay,
  readCommandLatencySamples,
  recordCommandLatency,
  sendLiveCommandWithAdaptiveHedge,
} from './liveCommandHedge.js';

const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
};

describe('adaptive live command hedge', () => {
  afterEach(() => {
    vi.useRealTimers();
    window.localStorage.clear();
  });

  it('uses a bounded rolling p90 after a cold start', () => {
    expect(commandHedgeDelay([])).toBe(1200);
    expect(commandHedgeDelay([800, 900, 1000, 1100, 1800].map((latency_ms) => ({ latency_ms })))).toBe(1800);
    expect(commandHedgeDelay([50, 80, 100, 120, 150].map((latency_ms) => ({ latency_ms })))).toBe(750);
    expect(commandHedgeDelay([2800, 2900, 3000, 3100, 3200].map((latency_ms) => ({ latency_ms })))).toBe(2500);
  });

  it('keeps only twenty recent original-attempt samples', () => {
    for (let index = 0; index < 25; index += 1) {
      recordCommandLatency(window.localStorage, 800 + index, 1_000 + index);
    }
    const samples = readCommandLatencySamples(window.localStorage, 2_000);
    expect(samples).toHaveLength(COMMAND_HEDGE_SAMPLE_LIMIT);
    expect(samples[0].latency_ms).toBe(805);
  });

  it('forgets samples older than seven days', () => {
    const now = 10 * 24 * 60 * 60 * 1000;
    recordCommandLatency(window.localStorage, 1800, now - (8 * 24 * 60 * 60 * 1000));
    expect(readCommandLatencySamples(window.localStorage, now)).toEqual([]);
    expect(commandHedgeDelay(readCommandLatencySamples(window.localStorage, now))).toBe(1200);
  });

  it('launches one hedge after the learned delay and cancels the losing original', async () => {
    vi.useFakeTimers();
    for (const latency of [800, 850, 900, 950, 1000]) recordCommandLatency(window.localStorage, latency, Date.now());
    const original = deferred();
    const hedge = deferred();
    const calls = [];
    const telemetry = vi.fn();
    const request = vi.fn(({ attempt, signal }) => {
      calls.push({ attempt, signal });
      return attempt === 'original' ? original.promise : hedge.promise;
    });

    const result = sendLiveCommandWithAdaptiveHedge(request, { storage: window.localStorage, onTelemetry: telemetry });
    await vi.advanceTimersByTimeAsync(999);
    expect(request).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1);
    expect(request).toHaveBeenCalledTimes(2);
    hedge.resolve({ accepted_version: 8 });
    await expect(result).resolves.toEqual({ accepted_version: 8 });
    expect(calls[0].signal.aborted).toBe(true);
    expect(telemetry).toHaveBeenCalledWith(expect.objectContaining({ attempts: 2, winner: 'hedge', loser_cancelled: true }));
  });

  it('does not hedge a fast terminal rejection', async () => {
    vi.useFakeTimers();
    const rejection = { status: 409, detail: { code: 'dice_live.stale_version' } };
    const request = vi.fn().mockRejectedValue(rejection);

    const result = sendLiveCommandWithAdaptiveHedge(request, { storage: window.localStorage });
    await expect(result).rejects.toBe(rejection);
    await vi.runAllTimersAsync();
    expect(request).toHaveBeenCalledTimes(1);
  });

  it('spends the remaining attempt immediately after a transport failure', async () => {
    vi.useFakeTimers();
    const telemetry = vi.fn();
    const request = vi.fn()
      .mockRejectedValueOnce(new Error('connection reset'))
      .mockResolvedValueOnce({ accepted_version: 8 });

    const result = sendLiveCommandWithAdaptiveHedge(request, {
      storage: window.localStorage,
      onTelemetry: telemetry,
    });
    await expect(result).resolves.toEqual({ accepted_version: 8 });
    expect(request).toHaveBeenCalledTimes(2);
    expect(request.mock.calls.map(([call]) => call.attempt)).toEqual(['original', 'retry']);
    expect(telemetry).toHaveBeenCalledWith(expect.objectContaining({
      attempts: 2,
      winner: 'retry',
      loser_cancelled: false,
    }));
  });

  it('waits for the original when a launched hedge fails in transport', async () => {
    vi.useFakeTimers();
    const original = deferred();
    const request = vi.fn(({ attempt }) => (
      attempt === 'original' ? original.promise : Promise.reject(new Error('hedge reset'))
    ));
    const result = sendLiveCommandWithAdaptiveHedge(request, { storage: window.localStorage });

    await vi.advanceTimersByTimeAsync(1200);
    original.resolve({ accepted_version: 8 });
    await expect(result).resolves.toEqual({ accepted_version: 8 });
    expect(request).toHaveBeenCalledTimes(2);
  });

  it('cancels a launched hedge when the original wins', async () => {
    vi.useFakeTimers();
    const original = deferred();
    const hedge = deferred();
    const calls = [];
    const request = vi.fn(({ attempt, signal }) => {
      calls.push({ attempt, signal });
      return attempt === 'original' ? original.promise : hedge.promise;
    });
    const result = sendLiveCommandWithAdaptiveHedge(request, { storage: window.localStorage });

    await vi.advanceTimersByTimeAsync(1200);
    original.resolve({ accepted_version: 8 });
    await expect(result).resolves.toEqual({ accepted_version: 8 });
    expect(calls[1].signal.aborted).toBe(true);
    expect(request).toHaveBeenCalledTimes(2);
  });
});
