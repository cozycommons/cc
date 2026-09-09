import { COMMONS_WORLD, getBackingStoreSize } from '../world/geometry.js';

export function observeCommonsViewport({ parent, scale, camera, environment = globalThis }) {
  let lastWidth = 0;
  let lastHeight = 0;
  function resize() {
    const bounds = parent.getBoundingClientRect();
    const side = Math.min(bounds.width, bounds.height);
    if (!Number.isFinite(side) || side <= 0) return;
    const { width, height } = getBackingStoreSize(side, side, environment.devicePixelRatio || 1);
    if (width === lastWidth && height === lastHeight) return;
    lastWidth = width;
    lastHeight = height;
    scale.setGameSize(width, height);
    camera.setSize(width, height);
    camera.setZoom(width / COMMONS_WORLD.width);
    camera.centerOn(COMMONS_WORLD.width / 2, COMMONS_WORLD.height / 2);
  }
  const observer = environment.ResizeObserver ? new environment.ResizeObserver(resize) : null;
  observer?.observe(parent);
  environment.addEventListener?.('resize', resize);
  resize();
  return () => {
    observer?.disconnect();
    environment.removeEventListener?.('resize', resize);
  };
}
