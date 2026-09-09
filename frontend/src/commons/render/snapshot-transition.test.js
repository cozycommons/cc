import { describe, expect, it, vi } from 'vitest';
import { createSnapshotTransition } from './snapshot-transition.js';

const flush = async () => { for (let i = 0; i < 10; i += 1) await Promise.resolve(); };
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
    h.controller.submit(scene(1)); await flush();
    h.controller.submit(scene(2)); await flush();
    expect(h.install.mock.calls.map(([value]) => value.version)).toEqual([1]);
    expect(h.fade).not.toHaveBeenCalled();
    expect(h.onError).toHaveBeenCalledOnce();
  });

  it('coalesces pending updates and rejects an older response during preload', async () => {
    let release;
    const h = harness(() => new Promise((resolve) => { release = resolve; }));
    h.controller.submit(scene(3));
    h.controller.submit(scene(2));
    release(); await flush();
    expect(h.install.mock.calls.map(([value]) => value.version)).toEqual([3]);
  });

  it('queues a paused snapshot and swaps atomically under reduced motion', async () => {
    const h = harness();
    h.controller.submit(scene(1)); await flush();
    h.controller.setPolicy({ paused: true });
    h.controller.submit(scene(2)); h.controller.submit(scene(3)); await flush();
    expect(h.install).toHaveBeenCalledTimes(1);
    h.controller.setPolicy({ reducedMotion: true }); await flush();
    expect(h.install.mock.calls.map(([value]) => value.version)).toEqual([1, 3]);
    expect(h.fade).not.toHaveBeenCalled();
  });

  it('fades around a replacement and ignores late preload completion after disposal', async () => {
    const h = harness();
    h.controller.submit(scene(1)); await flush();
    h.controller.submit(scene(2)); await flush();
    expect(h.fade.mock.calls).toEqual([[0], [1]]);
    let release;
    const pending = harness(() => new Promise((resolve) => { release = resolve; }));
    pending.controller.submit(scene(1)); pending.controller.dispose(); release(); await flush();
    expect(pending.install).not.toHaveBeenCalled();
  });
});
