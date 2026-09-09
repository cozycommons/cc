import React, { useEffect, useMemo, useRef, useState } from 'react';
import { getScene } from './sceneApi.js';
import { resolveMotionPolicy } from './ambient/motion-policy.js';
import { validateSceneSnapshot } from './world/contracts.js';
import './commons-scene.css';

const SCENE_FRESHNESS_MS = 30_000;

function actorCount(scene) {
  return Object.keys(scene?.state?.actors || {}).length;
}

function objectCount(scene) {
  return Object.keys(scene?.state?.objects || {}).length;
}

function describeScene(scene) {
  if (!scene) return 'The shared room is loading.';
  const people = actorCount(scene);
  const objects = objectCount(scene);
  return `The shared Commons room has ${people} resident${people === 1 ? '' : 's'} and ${objects} placed object${objects === 1 ? '' : 's'}.`;
}

function useMediaPreference(query) {
  const [matches, setMatches] = useState(false);

  useEffect(() => {
    const media = globalThis.matchMedia?.(query);
    if (!media) return undefined;
    const update = () => setMatches(Boolean(media.matches));
    update();
    media.addEventListener?.('change', update);
    media.addListener?.(update);
    return () => {
      media.removeEventListener?.('change', update);
      media.removeListener?.(update);
    };
  }, [query]);

  return matches;
}

function readPausePreference() {
  try {
    return window.localStorage.getItem('cozy-commons.scene-paused') === 'true';
  } catch {
    return false;
  }
}

function writePausePreference(paused) {
  try {
    window.localStorage.setItem('cozy-commons.scene-paused', String(paused));
  } catch {
    // A pause control still works when storage is unavailable.
  }
}

export default function CommonsScene() {
  const worldRef = useRef(null);
  const gameRef = useRef(null);
  const sceneRef = useRef(null);
  const latestSceneRef = useRef(null);
  const queuedSceneRef = useRef(null);
  const pausedRef = useRef(false);
  const refreshingRef = useRef(false);
  const [scene, setScene] = useState(null);
  const [paused, setPaused] = useState(readPausePreference);
  const [hidden, setHidden] = useState(Boolean(globalThis.document?.hidden));
  const [stale, setStale] = useState(false);
  const [status, setStatus] = useState('connecting to the room');
  const lastUsableRefreshAtRef = useRef(0);
  const staleRef = useRef(false);
  const reducedMotion = useMediaPreference('(prefers-reduced-motion: reduce)');
  const motionPolicy = useMemo(
    () => resolveMotionPolicy({ paused, reducedMotion, hidden, stale }),
    [hidden, paused, reducedMotion, stale],
  );
  const initialMotionPolicyRef = useRef(motionPolicy);
  if (!gameRef.current) initialMotionPolicyRef.current = motionPolicy;
  const hasScene = Boolean(scene);
  sceneRef.current = scene;
  pausedRef.current = paused;
  staleRef.current = stale;

  useEffect(() => {
    let active = true;

    async function refresh({ initial = false } = {}) {
      if (!active || refreshingRef.current || (!initial && document.hidden)) return;
      refreshingRef.current = true;
      try {
        const latest = await getScene();
        if (!active) return;
        const validation = validateSceneSnapshot(latest);
        if (!validation.valid) {
          setStatus('the room sent an unsupported snapshot');
          return;
        }
        const uncertaintyMs = Number(latest.__client_timing?.uncertainty_ms);
        const reliableTiming = !Number.isFinite(uncertaintyMs) || uncertaintyMs <= 500;
        if (reliableTiming) {
          lastUsableRefreshAtRef.current = Date.now();
          setStale(false);
        }
        const previous = latestSceneRef.current || sceneRef.current;
        latestSceneRef.current = latest;
        if (previous && pausedRef.current) {
          queuedSceneRef.current = latest;
          setStatus('a newer room snapshot is waiting');
          return;
        }
        sceneRef.current = latest;
        setScene((current) => {
          if (current && latest.version < current.version) return current;
          return latest;
        });
        if (!previous) setStatus('the room is shared');
        else if (latest.version > previous.version) setStatus('the room changed nearby');
        else if (staleRef.current && reliableTiming) setStatus('the room is shared');
      } catch {
        if (active && !sceneRef.current) setStatus('the room could not sync');
        // Keep showing the last canonical snapshot through a brief outage.
      } finally {
        refreshingRef.current = false;
      }
    }

    function markFreshness() {
      if (document.hidden || !sceneRef.current || !lastUsableRefreshAtRef.current) return;
      if (Date.now() - lastUsableRefreshAtRef.current >= SCENE_FRESHNESS_MS) {
        setStale(true);
        setStatus('the room could not sync');
      }
    }

    refresh({ initial: true });
    const interval = window.setInterval(() => {
      markFreshness();
      refresh();
    }, 8000);
    window.addEventListener('focus', refresh);
    window.addEventListener('online', refresh);
    const handleVisibility = () => {
      setHidden(Boolean(document.hidden));
      if (!document.hidden) {
        markFreshness();
        refresh();
      }
    };
    document.addEventListener('visibilitychange', handleVisibility);
    return () => {
      active = false;
      window.clearInterval(interval);
      window.removeEventListener('focus', refresh);
      window.removeEventListener('online', refresh);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, []);

  useEffect(() => {
    if (!hasScene || !worldRef.current || gameRef.current || import.meta.env.MODE === 'test') return undefined;
    let active = true;
    Promise.all([
      import('phaser'),
      import('./commons-phaser.js'),
    ]).then(([phaserModule, sceneModule]) => {
      if (!active || !worldRef.current) return;
      const Phaser = phaserModule.default;
      const game = sceneModule.createCommonsPhaserGame({
        Phaser,
        parent: worldRef.current,
        initialScene: sceneRef.current,
        motionPolicy: initialMotionPolicyRef.current,
        callbacks: {
          interactive: false,
          inspector: false,
          onAssetError: () => setStatus('the room is ready, but some art could not load'),
        },
      });
      gameRef.current = game;
      game.setMotionPolicy?.(initialMotionPolicyRef.current);
    }).catch(() => {
      if (active) setStatus('the room is ready, but its renderer could not start');
    });
    return () => {
      active = false;
      gameRef.current?.destroy(true);
      gameRef.current = null;
    };
  }, [hasScene]);

  useEffect(() => {
    gameRef.current?.syncState(scene);
  }, [scene]);

  useEffect(() => {
    gameRef.current?.setMotionPolicy?.(motionPolicy);
  }, [motionPolicy]);

  function togglePause() {
    const next = !paused;
    pausedRef.current = next;
    writePausePreference(next);
    if (!next && queuedSceneRef.current) {
      const queued = queuedSceneRef.current;
      queuedSceneRef.current = null;
      latestSceneRef.current = queued;
      sceneRef.current = queued;
      setScene(queued);
      setStatus('the room is up to date');
    }
    setPaused(next);
  }

  const displayStatus = paused ? 'the room is paused' : status;
  return (
    <div className="commons-scene" aria-label="Cozy Commons shared room">
      <div className="commons-room__image-wrap commons-scene__frame">
        <img
          className="commons-scene__fallback"
          src="/commons/cozy-commons-room-tile-base.png"
          alt=""
          aria-hidden="true"
        />
        <div
          className="commons-scene__phaser"
          ref={worldRef}
          role="img"
          aria-label="Ambient tile-based Commons room"
        />
        <div className="commons-scene__a11y">
          <p>{describeScene(scene)}</p>
        </div>
        <div className="commons-scene__instructions" aria-live="polite">
          <span className="commons-scene__status-dot" aria-hidden="true" />
          <span>{displayStatus}</span>
          <button
            className="commons-scene__pause"
            type="button"
            aria-pressed={paused}
            onClick={togglePause}
          >
            {paused ? 'resume room' : 'pause room'}
          </button>
        </div>
      </div>
    </div>
  );
}
