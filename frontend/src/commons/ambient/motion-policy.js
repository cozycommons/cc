export function resolveMotionPolicy({ paused = false, reducedMotion = false, hidden = false, stale = false } = {}) {
  const isPaused = Boolean(paused);
  const prefersReducedMotion = Boolean(reducedMotion);
  const isHidden = Boolean(hidden);
  const isStale = Boolean(stale);
  return Object.freeze({
    paused: isPaused,
    reducedMotion: prefersReducedMotion,
    hidden: isHidden,
    stale: isStale,
    animate: !(isPaused || prefersReducedMotion || isHidden || isStale),
  });
}
