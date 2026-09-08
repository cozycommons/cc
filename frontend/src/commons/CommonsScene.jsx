import React, { useEffect, useMemo, useRef, useState } from 'react';
import {
  clearPendingSceneCommand,
  getPendingSceneCommand,
  getScene,
  getSceneClientId,
  savePendingSceneCommand,
  sendSceneCommand,
} from './sceneApi.js';
import './commons-scene.css';

const ROOM_IMAGE = '/cozy-commons-room-empty.png';

function clamp(value, minimum = 0.08, maximum = 0.92) {
  return Math.min(maximum, Math.max(minimum, value));
}

function pointInWorld(event, element) {
  const bounds = element.getBoundingClientRect();
  return {
    x: clamp((event.clientX - bounds.left) / bounds.width),
    y: clamp((event.clientY - bounds.top) / bounds.height),
  };
}

function positionStyle(entity, preview) {
  const position = preview || entity;
  return { left: `${position.x * 100}%`, top: `${position.y * 100}%` };
}

export default function CommonsScene() {
  const worldRef = useRef(null);
  const dragRef = useRef(null);
  const lastPointerWasDragRef = useRef(false);
  const clientId = useMemo(() => getSceneClientId(), []);
  const [scene, setScene] = useState(null);
  const [dragPreview, setDragPreview] = useState(null);
  const [pending, setPending] = useState(false);
  const [status, setStatus] = useState('connecting to the room');

  useEffect(() => {
    let active = true;
    getScene()
      .then(async (loaded) => {
        if (!active) return;
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
          setScene((current) => ({
            ...(current || loaded),
            version: receipt.version,
            state: receipt.state,
          }));
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
      getScene()
        .then((latest) => {
          if (!active) return;
          setScene((current) => {
            if (!current || latest.version <= current.version) return current;
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
    if (!scene || pending) return;
    const command = {
      client_command_id: globalThis.crypto?.randomUUID?.() || `command-${Date.now()}`,
      expected_version: scene.version,
      kind,
      payload,
    };
    savePendingSceneCommand(command);
    setPending(true);
    setStatus('saving the room');
    try {
      const receipt = await sendSceneCommand(command, clientId);
      clearPendingSceneCommand(command.client_command_id);
      setScene((current) => ({
        ...current,
        version: receipt.version,
        state: receipt.state,
      }));
      setStatus(receipt.replayed ? 'your last change is still here' : 'saved to the shared room');
    } catch (error) {
      if (error.code === 'commons.stale_version') {
        clearPendingSceneCommand(command.client_command_id);
        setStatus('someone changed the room — refreshing');
        try {
          setScene(await getScene());
          setStatus('the room is up to date');
        } catch {
          setStatus('the room could not sync');
        }
      } else if (error.code === 'commons.command_id_conflict') {
        clearPendingSceneCommand(command.client_command_id);
        setStatus('that change could not be identified safely');
      } else {
        setStatus('that change could not be saved');
      }
    } finally {
      setPending(false);
    }
  }

  function handleWorldClick(event) {
    if (!scene) return;
    const point = pointInWorld(event, worldRef.current);
    commit('walk_actor', { actor_id: 'host', ...point });
  }

  function handleObjectPointerDown(event, object) {
    if (!object.movable || pending) return;
    event.stopPropagation();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    lastPointerWasDragRef.current = false;
    dragRef.current = { objectId: object.id, startX: event.clientX, startY: event.clientY, moved: false };
    setDragPreview({ objectId: object.id, x: object.x, y: object.y });
  }

  function handleObjectPointerMove(event) {
    if (!dragRef.current || !worldRef.current) return;
    if (Math.hypot(
      event.clientX - dragRef.current.startX,
      event.clientY - dragRef.current.startY,
    ) > 5) {
      dragRef.current.moved = true;
    }
    const point = pointInWorld(event, worldRef.current);
    setDragPreview({ objectId: dragRef.current.objectId, ...point });
  }

  function finishObjectDrag(event) {
    const drag = dragRef.current;
    if (!drag || !worldRef.current || !scene) return;
    const point = pointInWorld(event, worldRef.current);
    dragRef.current = null;
    setDragPreview(null);
    lastPointerWasDragRef.current = drag.moved;
    if (drag.moved) commit('move_object', { object_id: drag.objectId, ...point });
  }

  function toggleObject(event, object) {
    if (lastPointerWasDragRef.current) {
      lastPointerWasDragRef.current = false;
      return;
    }
    if (dragRef.current || !object.state) return;
    event.stopPropagation();
    const stateKey = Object.hasOwn(object.state, 'playing') ? 'playing' : 'on';
    commit('set_object_state', {
      object_id: object.id,
      state_key: stateKey,
      value: !object.state[stateKey],
    });
  }

  const objects = Object.values(scene?.state?.objects || {});
  const actors = Object.values(scene?.state?.actors || {});
  const host = actors.find((actor) => actor.id === 'host');

  return (
    <div className="commons-scene" aria-label="Interactive Cozy Commons room">
      <div
        className="commons-room__image-wrap commons-scene__frame"
        ref={worldRef}
        onPointerMove={handleObjectPointerMove}
        onPointerUp={finishObjectDrag}
        onPointerCancel={finishObjectDrag}
      >
        <img
          className="commons-room__image"
          src={ROOM_IMAGE}
          alt="An isometric living room in Cozy Commons"
          draggable="false"
        />
        <div className="commons-scene__world" onClick={handleWorldClick}>
          {objects.map((object) => {
            const preview = dragPreview?.objectId === object.id ? dragPreview : null;
            const active = object.state?.playing || object.state?.on;
            return (
              <button
                className={`commons-scene__entity commons-scene__object${active ? ' is-active' : ''}`}
                key={object.id}
                type="button"
                style={positionStyle(object, preview)}
                aria-label={`${object.id.replaceAll('-', ' ')}${active ? ' on' : ''}. Drag to move, click to change state.`}
                onClick={(event) => toggleObject(event, object)}
                onPointerDown={(event) => handleObjectPointerDown(event, object)}
              >
                <span aria-hidden="true">{object.id === 'record-player' ? '◉' : '☼'}</span>
              </button>
            );
          })}
          {host && (
            <div
              className="commons-scene__entity commons-scene__actor"
              style={positionStyle(host)}
              aria-label="Commons host"
            >
              <span aria-hidden="true">✦</span>
            </div>
          )}
        </div>
        <div className="commons-scene__instructions" aria-live="polite">
          <span className="commons-scene__status-dot" />
          <span>{status}</span>
          {scene && <span className="commons-scene__version">v{scene.version}</span>}
        </div>
      </div>
    </div>
  );
}
