export function resolveMotionPolicy({ paused = false, reducedMotion = false, hidden = false } = {}) {
  const isPaused = Boolean(paused);
  const prefersReducedMotion = Boolean(reducedMotion);
  const isHidden = Boolean(hidden);
  return Object.freeze({
    paused: isPaused,
    reducedMotion: prefersReducedMotion,
    hidden: isHidden,
    animate: !(isPaused || prefersReducedMotion || isHidden),
  });
}
