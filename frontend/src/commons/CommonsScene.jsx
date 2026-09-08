import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  clearPendingSceneCommand,
  getPendingSceneCommand,
  getScene,
  getSceneClientId,
  savePendingSceneCommand,
  sendSceneCommand,
} from './sceneApi.js';
import {
  findTilePath,
  isTileAvailable,
  normalizedToTile,
  normalizeTile,
} from './commons-grid.js';
import './commons-scene.css';

function entityTile(entity) {
  if (Number.isFinite(entity?.tile_x) && Number.isFinite(entity?.tile_y)) {
    return normalizeTile(entity.tile_x, entity.tile_y);
  }
  return normalizedToTile(entity?.x, entity?.y);
}

function entityLabel(entity) {
  if (entity.label) return entity.label;
  if (entity.id === 'host') return 'Commons host';
  return entity.id.replaceAll('-', ' ');
}

export default function CommonsScene() {
  const worldRef = useRef(null);
  const gameRef = useRef(null);
  const commitRef = useRef(null);
  const walkRef = useRef(null);
  const objectDropRef = useRef(null);
  const objectClickRef = useRef(null);
  const objectRotateRef = useRef(null);
  const sceneRef = useRef(null);
  const pendingRef = useRef(false);
  const walkingRef = useRef(false);
  const clientId = useMemo(() => getSceneClientId(), []);
  const [scene, setScene] = useState(null);
  const [pending, setPending] = useState(false);
  const [status, setStatus] = useState('connecting to the room');
  const hasScene = Boolean(scene);
  sceneRef.current = scene;
  pendingRef.current = pending;

  useEffect(() => {
    let active = true;
    getScene()
      .then(async (loaded) => {
        if (!active) return;
        sceneRef.current = loaded;
        setScene(loaded);
        setStatus('the room is shared');
        const pendingCommand = getPendingSceneCommand();
        if (!pendingCommand) return;
        setPending(true);
        setStatus('finishing the last room change');
        try {
          const receipt = await sendSceneCommand(pendingCommand, clientId);
          clearPendingSceneCommand(pendingCommand.client_command_id);
          if (!active) return;
          const nextScene = {
            ...(sceneRef.current || loaded),
            version: receipt.version,
            state: receipt.state,
          };
          sceneRef.current = nextScene;
          setScene(nextScene);
          setStatus(receipt.replayed ? 'your last change is still here' : 'saved to the shared room');
        } catch (error) {
          if (error.code !== 'commons.stale_version') {
            setStatus('the last room change is waiting to retry');
          } else {
            clearPendingSceneCommand(pendingCommand.client_command_id);
            setStatus('the room is up to date');
          }
        } finally {
          if (active) setPending(false);
        }
      })
      .catch(() => {
        if (active) setStatus('the room could not sync');
      });
    return () => { active = false; };
  }, [clientId]);

  useEffect(() => {
    if (!scene || pending) return undefined;
    let active = true;
    const refresh = () => {
      if (walkingRef.current) return;
      getScene()
        .then((latest) => {
          if (!active) return;
          setScene((current) => {
            if (!current || latest.version <= current.version) return current;
            sceneRef.current = latest;
            setStatus('the room changed nearby');
            return latest;
          });
        })
        .catch(() => {
          // The last canonical scene remains usable during a brief outage.
        });
    };
    const interval = window.setInterval(refresh, 8000);
    window.addEventListener('focus', refresh);
    window.addEventListener('online', refresh);
    return () => {
      active = false;
      window.clearInterval(interval);
      window.removeEventListener('focus', refresh);
      window.removeEventListener('online', refresh);
    };
  }, [scene, pending]);

  async function commit(kind, payload) {
    const currentScene = sceneRef.current;
    if (!currentScene || pendingRef.current) return null;
    const command = {
      client_command_id: globalThis.crypto?.randomUUID?.() || `command-${Date.now()}`,
      expected_version: currentScene.version,
      kind,
      payload,
    };
    savePendingSceneCommand(command);
    pendingRef.current = true;
    setPending(true);
    setStatus('saving the room');
    try {
      const receipt = await sendSceneCommand(command, clientId);
      clearPendingSceneCommand(command.client_command_id);
      const nextScene = {
        ...sceneRef.current,
        version: receipt.version,
        state: receipt.state,
      };
      sceneRef.current = nextScene;
      setScene(nextScene);
      setStatus(receipt.replayed ? 'your last change is still here' : 'saved to the shared room');
      return nextScene;
    } catch (error) {
      if (error.code === 'commons.stale_version') {
        clearPendingSceneCommand(command.client_command_id);
        setStatus('someone changed the room — refreshing');
        try {
          const latest = await getScene();
          sceneRef.current = latest;
          setScene(latest);
          setStatus('the room is up to date');
        } catch {
          setStatus('the room could not sync');
        }
      } else if (error.code === 'commons.command_id_conflict') {
        clearPendingSceneCommand(command.client_command_id);
        setStatus('that change could not be identified safely');
      } else if (error.code === 'commons.tile_occupied' || error.code === 'commons.tile_blocked') {
        clearPendingSceneCommand(command.client_command_id);
        setStatus('that tile is occupied');
      } else {
        setStatus('that change could not be saved');
      }
      gameRef.current?.syncState(sceneRef.current);
      return null;
    } finally {
      pendingRef.current = false;
      setPending(false);
    }
  }

  function markActorWalking(tile) {
    const target = normalizeTile(tile.tile_x, tile.tile_y);
    gameRef.current?.drawTarget(target);
  }

  function handleWalkTile(tile) {
    const currentScene = sceneRef.current;
    if (!currentScene || pendingRef.current || walkingRef.current) return;
    if (!isTileAvailable(currentScene.state, tile, { entityType: 'actor', entityId: 'host' })) {
      setStatus('that tile is occupied');
      return;
    }
    const actor = currentScene.state.actors?.host;
    const path = findTilePath(
      currentScene.state,
      entityTile(actor),
      tile,
      { entityType: 'actor', entityId: 'host' },
    );
    if (!path.length) return;
    markActorWalking(tile);
    walkingRef.current = true;
    gameRef.current?.walkActorPath('host', path);
    let completed = false;
    (async () => {
      try {
        for (const step of path) {
          const nextScene = await commit('walk_actor', { actor_id: 'host', ...step });
          if (!nextScene) return;
        }
        completed = true;
      } finally {
        gameRef.current?.finishActorWalk('host', completed);
        walkingRef.current = false;
      }
    })();
  }

  function handleObjectDrop(objectId, tile) {
    const currentScene = sceneRef.current;
    const nextTile = normalizeTile(tile.tile_x, tile.tile_y);
    if (!currentScene || pendingRef.current || walkingRef.current) {
      gameRef.current?.syncState(currentScene);
      return;
    }
    if (!isTileAvailable(currentScene.state, nextTile, { entityType: 'object', entityId: objectId })) {
      gameRef.current?.syncState(currentScene);
      setStatus('that tile is occupied');
      return;
    }
    commit('move_object', { object_id: objectId, ...nextTile });
  }

  function toggleObjectById(objectId) {
    const object = sceneRef.current?.state?.objects?.[objectId];
    if (!object || pendingRef.current || walkingRef.current || !object.state) return;
    const stateKey = ['playing', 'on'].find((key) => Object.hasOwn(object.state, key));
    if (!stateKey) return;
    commit('set_object_state', {
      object_id: object.id,
      state_key: stateKey,
      value: !object.state[stateKey],
    });
  }

  function rotateObjectById(objectId) {
    const object = sceneRef.current?.state?.objects?.[objectId];
    if (!object || pendingRef.current || walkingRef.current || object.movable !== true) return;
    commit('rotate_object', {
      object_id: object.id,
      orientation: object.orientation === 'north' ? 'south' : 'north',
    });
  }

  commitRef.current = commit;
  walkRef.current = handleWalkTile;
  objectDropRef.current = handleObjectDrop;
  objectClickRef.current = toggleObjectById;
  objectRotateRef.current = rotateObjectById;

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
        callbacks: {
          onWalkTile: (tile) => walkRef.current?.(tile),
          onObjectDrop: (objectId, tile) => objectDropRef.current?.(objectId, tile),
          onObjectClick: (objectId) => objectClickRef.current?.(objectId),
          onObjectRotate: (objectId) => objectRotateRef.current?.(objectId),
          onBlockedTile: () => setStatus('that tile is occupied'),
          onInvalidObjectDrop: () => setStatus('that tile is occupied'),
        },
      });
      gameRef.current = game;
    }).catch(() => {
      if (active) setStatus('the room is ready, but its game renderer could not start');
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
    function handleKeyDown(event) {
      if (!scene || event.repeat) return;
      if (event.target instanceof HTMLInputElement || event.target instanceof HTMLTextAreaElement) return;
      if (event.key === 'g' || event.key === 'G') {
        event.preventDefault();
        gameRef.current?.toggleGrid();
        return;
      }
      if (pending || walkingRef.current) return;
      const direction = {
        ArrowLeft: [-1, 0], a: [-1, 0], A: [-1, 0],
        ArrowRight: [1, 0], d: [1, 0], D: [1, 0],
        ArrowUp: [0, -1], w: [0, -1], W: [0, -1],
        ArrowDown: [0, 1], s: [0, 1], S: [0, 1],
      }[event.key];
      if (!direction) return;
      const host = scene.state.actors?.host;
      if (!host) return;
      event.preventDefault();
      const tile = entityTile(host);
      const next = normalizeTile(tile.tile_x + direction[0], tile.tile_y + direction[1]);
      walkRef.current?.(next);
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [scene, pending]);

  const objects = Object.values(scene?.state?.objects || {});
  const actors = Object.values(scene?.state?.actors || {});

  return (
    <div className="commons-scene" aria-label="Interactive Cozy Commons room">
      <div className="commons-room__image-wrap commons-scene__frame">
        <div className="commons-scene__phaser" ref={worldRef} aria-label="Tile-based Commons game world" />
        <div className="commons-scene__a11y">
          {objects.map((object) => (
            <button
              key={object.id}
              type="button"
              aria-label={`${entityLabel(object)}${object.state?.playing || object.state?.on ? ' on' : ''}. Tile ${entityTile(object).tile_x}, ${entityTile(object).tile_y}`}
              onClick={() => toggleObjectById(object.id)}
            >
              {entityLabel(object)}
            </button>
          ))}
          {objects.filter((object) => object.movable === true).map((object) => (
            <button
              key={`${object.id}-rotate`}
              type="button"
              aria-label={`Rotate ${entityLabel(object)}`}
              onClick={() => rotateObjectById(object.id)}
            >
              Rotate {entityLabel(object)}
            </button>
          ))}
          {actors.map((actor) => (
            <span key={actor.id} aria-label={entityLabel(actor)}>
              {entityLabel(actor)}
            </span>
          ))}
        </div>
        <div className="commons-scene__instructions" aria-live="polite">
          <span className="commons-scene__status-dot" />
          <span>{status}</span>
          {scene && <span className="commons-scene__version">v{scene.version}</span>}
          <span className="commons-scene__controls">click or WASD to walk · drag furniture · right-click to rotate · G tile grid</span>
        </div>
      </div>
    </div>
  );
}
