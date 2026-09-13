import { describe, expect, it, vi } from 'vitest';
import { createSnapshotTransition } from './snapshot-transition.js';

const waitForIdle = async (controller) => {
  await vi.waitFor(() => expect(controller.isTransitioning()).toBe(false));
};
const scene = (version) => ({ version, state: { ambient: { revision: version } } });
function harness(prepare = async () => {}) {
  const install = vi.fn();
  const fade = vi.fn(async () => {});
  const onError = vi.fn();
  const controller = createSnapshotTransition({ prepare, install, fade, cancelFade: vi.fn(), onError });
  return { controller, install, fade, onError };
}

describe('Whole-snapshot transitions', () => {
  it('keeps the complete previous snapshot when candidate preparation fails', async () => {
    const h = harness(async (candidate) => { if (candidate.version === 2) throw new Error('missing atlas'); });
    h.controller.submit(scene(1)); await waitForIdle(h.controller);
    h.controller.submit(scene(2)); await waitForIdle(h.controller);
    expect(h.install.mock.calls.map(([value]) => value.version)).toEqual([1]);
    expect(h.fade).not.toHaveBeenCalled();
    expect(h.onError).toHaveBeenCalledOnce();
  });

  it('coalesces pending updates and rejects an older response during preload', async () => {
    let release;
    const h = harness(() => new Promise((resolve) => { release = resolve; }));
    h.controller.submit(scene(3));
    h.controller.submit(scene(2));
    release(); await waitForIdle(h.controller);
    expect(h.install.mock.calls.map(([value]) => value.version)).toEqual([3]);
  });

  it('queues a paused snapshot and swaps atomically under reduced motion', async () => {
    const h = harness();
    h.controller.submit(scene(1)); await waitForIdle(h.controller);
    h.controller.setPolicy({ paused: true });
    h.controller.submit(scene(2)); h.controller.submit(scene(3)); await waitForIdle(h.controller);
    expect(h.install).toHaveBeenCalledTimes(1);
    h.controller.setPolicy({ reducedMotion: true }); await waitForIdle(h.controller);
    expect(h.install.mock.calls.map(([value]) => value.version)).toEqual([1, 3]);
    expect(h.fade).not.toHaveBeenCalled();
  });

  it('fades around a replacement and ignores late preload completion after disposal', async () => {
    const h = harness();
    h.controller.submit(scene(1)); await waitForIdle(h.controller);
    h.controller.submit(scene(2)); await waitForIdle(h.controller);
    expect(h.fade.mock.calls).toEqual([[0], [1]]);
    let release;
    const pending = harness(() => new Promise((resolve) => { release = resolve; }));
    pending.controller.submit(scene(1)); pending.controller.dispose(); release(); await waitForIdle(pending.controller);
    expect(pending.install).not.toHaveBeenCalled();
  });
});
