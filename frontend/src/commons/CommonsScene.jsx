import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  clearPendingSceneCommand,
  getScene,
  sendSceneCommand,
  savePendingSceneCommand,
} from './sceneApi.js';
import { findTilePath, normalizeTile } from './commons-grid.js';
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
  return `A top-down tile-based Cozy Commons room with ${people} resident${people === 1 ? '' : 's'} and ${objects} placed object${objects === 1 ? '' : 's'}, including a bed, work table, fireplace, and bookcase.`;
}

function newCommandId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `room-${Date.now()}-${Math.random().toString(36).slice(2)}`;
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
  const [status, setStatus] = useState('Use WASD or the arrow keys to explore the room.');
  const [hidden, setHidden] = useState(Boolean(globalThis.document?.hidden));
  const [stale, setStale] = useState(false);
  const lastUsableRefreshAtRef = useRef(0);
  const commandBusyRef = useRef(false);
  const walkTargetRef = useRef(null);
  const staleRef = useRef(stale);
  const mountedRef = useRef(true);
  const reducedMotion = useMediaPreference('(prefers-reduced-motion: reduce)');
  const motionPolicy = useMemo(
    () => resolveMotionPolicy({ reducedMotion, hidden, stale }),
    [hidden, reducedMotion, stale],
  );
  const initialMotionPolicyRef = useRef(motionPolicy);
  if (!gameRef.current) initialMotionPolicyRef.current = motionPolicy;
  const hasScene = Boolean(scene);
  sceneRef.current = scene;
  staleRef.current = stale;

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
      mountedRef.current = false;
      window.clearInterval(interval);
      window.removeEventListener('focus', refresh);
      window.removeEventListener('online', refresh);
      document.removeEventListener('visibilitychange', handleVisibility);
    };
  }, []);

  useEffect(() => {
    mountedRef.current = true;
    return () => { mountedRef.current = false; };
  }, []);

  async function applyCommand(kind, payload) {
    const current = sceneRef.current;
    if (!current || commandBusyRef.current) return false;
    const command = {
      client_command_id: newCommandId(),
      expected_version: current.version,
      kind,
      payload,
    };
    commandBusyRef.current = true;
    savePendingSceneCommand(command);
    try {
      const receipt = await sendSceneCommand(command);
      if (!mountedRef.current || !receipt?.state) return false;
      const next = {
        ...current,
        version: receipt.version,
        state: receipt.state,
      };
      sceneRef.current = next;
      setScene(next);
      clearPendingSceneCommand(command.client_command_id);
      setStale(false);
      setStatus('The room is shared — your change is saved.');
      return true;
    } catch (error) {
      if (error?.currentVersion !== undefined) {
        setStatus('The room changed elsewhere. Refreshing the latest layout.');
        try {
          const latest = await getScene();
          if (mountedRef.current && validateSceneSnapshot(latest).valid) {
            sceneRef.current = latest;
            setScene(latest);
          }
        } catch {
          setStatus('The room is temporarily offline; the last valid layout is still visible.');
        }
      } else {
        setStatus('The room is temporarily offline; that change was not applied.');
      }
      return false;
    } finally {
      commandBusyRef.current = false;
    }
  }

  async function drainWalkTarget() {
    if (commandBusyRef.current) return;
    while (walkTargetRef.current && mountedRef.current) {
      const current = sceneRef.current;
      const host = current?.state?.actors?.host;
      if (!current || !host) break;
      const start = normalizeTile(host.tile_x, host.tile_y);
      const target = walkTargetRef.current;
      const path = findTilePath(current.state, start, target, { entityType: 'actor', entityId: 'host' });
      const next = path[0];
      if (!next) {
        walkTargetRef.current = null;
        break;
      }
      const accepted = await applyCommand('walk_actor', {
        actor_id: 'host',
        tile_x: next.tile_x,
        tile_y: next.tile_y,
      });
      if (!accepted) {
        walkTargetRef.current = null;
        break;
      }
      if (next.tile_x === target.tile_x && next.tile_y === target.tile_y) walkTargetRef.current = null;
    }
  }

  function requestWalk(tile) {
    if (!sceneRef.current || staleRef.current) return;
    walkTargetRef.current = normalizeTile(tile?.tile_x, tile?.tile_y);
    gameRef.current?.drawTarget?.(walkTargetRef.current);
    void drainWalkTarget();
  }

  function requestWalkDirection(delta) {
    const host = sceneRef.current?.state?.actors?.host;
    if (!host) return;
    requestWalk({ tile_x: host.tile_x + delta.tile_x, tile_y: host.tile_y + delta.tile_y });
  }

  function requestObjectDrop(objectId, tile) {
    void applyCommand('move_object', { object_id: objectId, tile_x: tile.tile_x, tile_y: tile.tile_y });
  }

  function requestObjectRotate(objectId) {
    const object = sceneRef.current?.state?.objects?.[objectId];
    const orientation = object?.orientation === 'north' ? 'south' : 'north';
    void applyCommand('rotate_object', { object_id: objectId, orientation });
  }

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
          interactive: true,
          inspector: false,
          onWalkTile: requestWalk,
          onWalkDirection: requestWalkDirection,
          onObjectDrop: requestObjectDrop,
          onObjectRotate: requestObjectRotate,
          onCancelInteraction: () => {
            walkTargetRef.current = null;
            gameRef.current?.drawTarget?.(null);
          },
          onInvalidObjectDrop: () => setStatus('That furniture footprint does not fit there.'),
          onBlockedTile: () => setStatus('That tile is blocked by the room or furniture.'),
          onObjectClick: () => setStatus('Drag a piece of furniture to rearrange the room.'),
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
          src="/commons/cozy-room-shell.png"
          alt=""
          aria-hidden="true"
        />
        <div
          className="commons-scene__phaser"
          ref={worldRef}
          role="img"
          aria-label="Interactive top-down tile-based Cozy Commons room"
        />
        <div className="commons-scene__controls" aria-live="polite">
          <span>WASD / arrows to walk · click a tile to pathfind · drag furniture</span>
          <span>{status}</span>
        </div>
        <div className="commons-scene__a11y">
          <p>{describeScene(scene)}</p>
        </div>
      </div>
    </div>
  );
}
