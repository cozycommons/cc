import { describe, expect, it, vi } from 'vitest';
import { observeCommonsViewport } from './viewport.js';

describe('Commons responsive backing store', () => {
  it('scales the buffer and camera together without changing logical world coordinates', () => {
    let bounds = { width: 720, height: 720 };
    let onResize;
    const disconnect = vi.fn();
    const environment = {
      devicePixelRatio: 2,
      ResizeObserver: class {
        constructor(callback) { onResize = callback; }
        observe() {}
        disconnect = disconnect;
      },
      addEventListener: vi.fn(), removeEventListener: vi.fn(),
    };
    const scale = { setGameSize: vi.fn() };
    const camera = { setSize: vi.fn(), setZoom: vi.fn(), centerOn: vi.fn() };
    const dispose = observeCommonsViewport({
      parent: { getBoundingClientRect: () => bounds }, scale, camera, environment,
    });
    expect(scale.setGameSize).toHaveBeenLastCalledWith(1440, 1440);
    expect(camera.setZoom).toHaveBeenLastCalledWith(1440 / 512);
    expect(camera.centerOn).toHaveBeenLastCalledWith(256, 256);
    onResize();
    expect(scale.setGameSize).toHaveBeenCalledTimes(1);
    bounds = { width: 358, height: 358 };
    onResize();
    expect(scale.setGameSize).toHaveBeenLastCalledWith(716, 716);
    environment.devicePixelRatio = 3;
    onResize();
    expect(scale.setGameSize).toHaveBeenCalledTimes(2);
    environment.devicePixelRatio = 1;
    onResize();
    expect(scale.setGameSize).toHaveBeenLastCalledWith(358, 358);
    bounds = { width: 0, height: 0 };
    onResize();
    expect(scale.setGameSize).toHaveBeenCalledTimes(3);
    dispose();
    expect(disconnect).toHaveBeenCalledOnce();
    expect(environment.removeEventListener).toHaveBeenCalledWith('resize', onResize);
  });
});
