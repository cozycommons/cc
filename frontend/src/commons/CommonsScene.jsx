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
  return `A warmly lit common room with ${people} resident${people === 1 ? '' : 's'} and ${objects} placed object${objects === 1 ? '' : 's'}, including plants and a listening nook.`;
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

export default function CommonsScene() {
  const worldRef = useRef(null);
  const gameRef = useRef(null);
  const sceneRef = useRef(null);
  const [scene, setScene] = useState(null);
  const [hidden, setHidden] = useState(Boolean(globalThis.document?.hidden));
  const [stale, setStale] = useState(false);
  const lastUsableRefreshAtRef = useRef(0);
  const reducedMotion = useMediaPreference('(prefers-reduced-motion: reduce)');
  const motionPolicy = useMemo(
    () => resolveMotionPolicy({ reducedMotion, hidden, stale }),
    [hidden, reducedMotion, stale],
  );
  const initialMotionPolicyRef = useRef(motionPolicy);
  if (!gameRef.current) initialMotionPolicyRef.current = motionPolicy;
  const hasScene = Boolean(scene);
  sceneRef.current = scene;

  useEffect(() => {
    let active = true;
    let refreshing = false;

    async function refresh({ initial = false } = {}) {
      if (!active || refreshing || (!initial && document.hidden)) return;
      refreshing = true;
      try {
        const latest = await getScene();
        if (!active) return;
        const validation = validateSceneSnapshot(latest);
        if (!validation.valid) {
          return;
        }
        if (sceneRef.current && latest.version < sceneRef.current.version) return;
        const uncertaintyMs = Number(latest.__client_timing?.uncertainty_ms);
        const reliableTiming = !Number.isFinite(uncertaintyMs) || uncertaintyMs <= 500;
        if (reliableTiming) {
          lastUsableRefreshAtRef.current = Date.now();
          setStale(false);
        }
        sceneRef.current = latest;
        setScene(latest);
      } catch {
        // Keep showing the last canonical snapshot through a brief outage.
      } finally {
        refreshing = false;
      }
    }

    function markFreshness() {
      if (document.hidden || !sceneRef.current || !lastUsableRefreshAtRef.current) return;
      if (Date.now() - lastUsableRefreshAtRef.current >= SCENE_FRESHNESS_MS) {
        setStale(true);
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
        },
      });
      gameRef.current = game;
      game.setMotionPolicy?.(initialMotionPolicyRef.current);
    }).catch(() => {
      // The static fallback remains visible when the optional renderer fails.
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
      </div>
    </div>
  );
}
