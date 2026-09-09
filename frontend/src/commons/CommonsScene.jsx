import React, { useEffect, useMemo, useRef, useState } from 'react';
import { getScene } from './sceneApi.js';
import { resolveMotionPolicy } from './ambient/motion-policy.js';
import './commons-scene.css';

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

export default function CommonsScene() {
  const worldRef = useRef(null);
  const gameRef = useRef(null);
  const sceneRef = useRef(null);
  const refreshingRef = useRef(false);
  const [scene, setScene] = useState(null);
  const [paused, setPaused] = useState(false);
  const [hidden, setHidden] = useState(Boolean(globalThis.document?.hidden));
  const [status, setStatus] = useState('connecting to the room');
  const reducedMotion = useMediaPreference('(prefers-reduced-motion: reduce)');
  const motionPolicy = useMemo(
    () => resolveMotionPolicy({ paused, reducedMotion, hidden }),
    [hidden, paused, reducedMotion],
  );
  const hasScene = Boolean(scene);
  sceneRef.current = scene;

  useEffect(() => {
    const updateVisibility = () => setHidden(Boolean(document.hidden));
    document.addEventListener('visibilitychange', updateVisibility);
    return () => document.removeEventListener('visibilitychange', updateVisibility);
  }, []);

  useEffect(() => {
    let active = true;

    async function refresh({ initial = false } = {}) {
      if (!active || refreshingRef.current || (!initial && document.hidden)) return;
      refreshingRef.current = true;
      try {
        const latest = await getScene();
        if (!active) return;
        const previous = sceneRef.current;
        sceneRef.current = latest;
        setScene((current) => {
          if (current && latest.version < current.version) return current;
          return latest;
        });
        if (!previous) setStatus('the room is shared');
        else if (latest.version > previous.version) setStatus('the room changed nearby');
      } catch {
        if (active && !sceneRef.current) setStatus('the room could not sync');
        // Keep showing the last canonical snapshot through a brief outage.
      } finally {
        refreshingRef.current = false;
      }
    }

    refresh({ initial: true });
    const interval = window.setInterval(() => refresh(), 8000);
    window.addEventListener('focus', refresh);
    window.addEventListener('online', refresh);
    return () => {
      active = false;
      window.clearInterval(interval);
      window.removeEventListener('focus', refresh);
      window.removeEventListener('online', refresh);
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
        callbacks: { interactive: false, inspector: false },
      });
      gameRef.current = game;
      game.setMotionPolicy?.(motionPolicy);
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

  const displayStatus = paused ? 'the room is paused' : status;
  return (
    <div className="commons-scene" aria-label="Cozy Commons shared room">
      <div className="commons-room__image-wrap commons-scene__frame">
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
            onClick={() => setPaused((current) => !current)}
          >
            {paused ? 'resume room' : 'pause room'}
          </button>
        </div>
      </div>
    </div>
  );
}
