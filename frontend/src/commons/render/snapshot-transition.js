export function createSnapshotTransition({
  prepare,
  install,
  fade,
  cancelFade,
  needsCorrection = () => false,
  shouldFade,
  onError = () => {},
}) {
  let current = null;
  let pending = null;
  let busy = false;
  let activeVersion = -1;
  let disposed = false;
  let policy = {};
  const frozen = () => policy.paused || policy.hidden;

  async function drain() {
    if (busy || disposed || frozen() || !pending) return;
    busy = true;
    try {
      while (pending && !disposed && !frozen()) {
        const candidate = pending;
        activeVersion = candidate.version;
        pending = null;
        try {
          await prepare(candidate);
          if (disposed) break;
          if (pending) continue;
          if (frozen()) { pending = candidate; break; }
          const changesWorld = current && (shouldFade
            ? shouldFade(candidate, current)
            : candidate.version !== current.version
              || candidate.state?.ambient?.revision !== current.state?.ambient?.revision
              || needsCorrection());
          if (changesWorld && !policy.reducedMotion) await fade(0);
          if (disposed) break;
          if (frozen()) { pending ??= candidate; break; }
          if (pending) continue;
          install(candidate);
          current = candidate;
          if (changesWorld && !policy.reducedMotion) await fade(1);
        } catch (error) {
          if (!disposed) onError(error);
        }
      }
    } finally {
      if (!disposed) cancelFade();
      busy = false;
      activeVersion = -1;
      if (!disposed && pending && !frozen()) void drain();
    }
  }

  return {
    submit(candidate) {
      if (disposed || !candidate) return;
      const newestVersion = Math.max(current?.version ?? -1, pending?.version ?? -1, activeVersion);
      if (candidate.version < newestVersion) return;
      pending = candidate;
      void drain();
    },
    setPolicy(next) {
      policy = next;
      if (frozen() || policy.reducedMotion) cancelFade();
      void drain();
    },
    isTransitioning: () => busy,
    dispose() {
      disposed = true;
      pending = null;
      cancelFade();
    },
  };
}
