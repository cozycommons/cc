import {
  COMMONS_ACTOR_ANIMATIONS,
  COMMONS_ASSETS,
  getCommonsActorAnimation,
  getCommonsActorTint,
  getCommonsAsset,
  getCommonsHitbox,
  getCommonsRenderMetadata,
  shouldMirrorCommonsAsset,
} from './commons-assets.js';
import {
  COMMONS_GRID,
  getEntityFootprint,
  isTileAvailable,
  normalizeTile,
  normalizedToTile,
  pixelToTile,
  tileDistance,
  tileKey,
} from './commons-grid.js';
import { evaluateAmbientPose, settleAmbientPose, validateAmbientProgram } from './ambient/timeline.js';
import { createPresentationClock } from './ambient/clock.js';
import { depthForGround, directionForDelta, projectGround } from './world/geometry.js';
import { createSnapshotTransition } from './render/snapshot-transition.js';
import { supportDepthOffset } from './render/grounding.js';
import { observeCommonsViewport } from './render/viewport.js';
import { validateSceneSnapshot } from './world/contracts.js';

const ROOM_WIDTH = COMMONS_GRID.width;
const ROOM_HEIGHT = COMMONS_GRID.height;
const ROOM_ASSET = '/commons/cozy-room-shell.png';
const FLOOR_ATLAS = '/commons/commons-floor-atlas.png';
export const COMMONS_SNAPSHOT_FADE_MS = 200;
const STATIC_ORIENTATIONS = ['south', 'north'];

function entityOrientation(entity) {
  return typeof entity?.orientation === 'string' && entity.orientation
    ? entity.orientation
    : typeof entity?.facing === 'string' && entity.facing
      ? entity.facing
      : 'south';
}

function textureRequest(key, path, kind = 'image', options = {}) {
  return {
    key,
    path,
    kind,
    ...options,
  };
}

/**
 * Return the immutable texture set needed to display a scene. Static assets
 * can expose an alternate orientation; callers that are preparing a complete
 * pack can request those too. The renderer only installs a scene after every
 * returned request is present in Phaser's texture manager.
 */
export function getCommonsSnapshotTextureRequests(
  scene,
  { includeStaticOrientations = false, inspector = false } = {},
) {
  const requests = new Map();
  const add = (request) => {
    if (!request?.key || !request.path || requests.has(request.key)) return;
    requests.set(request.key, request);
  };

  add(textureRequest('commons-room-base', ROOM_ASSET));
  if (inspector) {
    add(textureRequest('commons-floor-atlas', FLOOR_ATLAS, 'spritesheet', {
      frameWidth: 256,
      frameHeight: 256,
    }));
  }

  entitiesFromScene(scene).forEach((entity) => {
    const animation = entity.entityType === 'actor'
      ? getCommonsActorAnimation(entity.asset)
      : null;
    if (animation) {
      add(textureRequest(actorAnimationTextureKey(entity.asset), animation.path, 'spritesheet', {
        frameWidth: animation.frameWidth,
        frameHeight: animation.frameHeight,
      }));
      return;
    }

    const selectedOrientation = entityOrientation(entity);
    const orientations = includeStaticOrientations
      ? [...new Set([selectedOrientation, ...STATIC_ORIENTATIONS])]
      : [selectedOrientation];
    orientations.forEach((orientation) => {
      add(textureRequest(
        staticAssetTextureKey(entity.asset, orientation),
        getCommonsAsset(entity.asset, orientation),
      ));
    });
  });

  return [...requests.values()];
}

export function validateCommonsSnapshotCandidate(snapshot) {
  return validateSceneSnapshot(snapshot);
}

export function sortCommonsEntities(entities) {
  return [...entities].sort((first, second) => {
    const firstKey = `${first.entityType}:${first.id}`;
    const secondKey = `${second.entityType}:${second.id}`;
    return firstKey.localeCompare(secondKey);
  });
}

function entitiesFromScene(scene) {
  const objects = Object.values(scene?.state?.objects || {}).map((entity) => ({
    ...entity,
    entityType: 'object',
  }));
  const actors = Object.values(scene?.state?.actors || {}).map((entity) => ({
    ...entity,
    entityType: 'actor',
  }));
  return sortCommonsEntities(
    [...objects, ...actors].filter((entity) => entity.visible !== false && entity.hidden !== true),
  );
}

function entityTile(entity) {
  if (Number.isFinite(entity?.tile_x) && Number.isFinite(entity?.tile_y)) {
    return normalizeTile(entity.tile_x, entity.tile_y);
  }
  return normalizedToTile(entity?.x, entity?.y);
}

function staticAssetTextureKey(asset, orientation = 'south') {
  return `commons-static-${asset}-${orientation}`;
}

function actorAnimationTextureKey(asset) {
  return `actor-animation-${asset}`;
}

function actorAnimationKey(asset) {
  return `commons-${asset}-walk`;
}

function homeFacing(actor) {
  const facing = actor?.view || actor?.facing;
  if (['front', 'back', 'left', 'right'].includes(facing)) return facing;
  return {
    north: 'back',
    south: 'front',
    east: 'right',
    west: 'left',
  }[facing] || 'front';
}

function isLeftFacing(facing) {
  return facing === 'left';
}

function drawDiamond(graphics, tileX, tileY, options = {}) {
  const point = projectGround(tileX, tileY);
  const x = point.x - COMMONS_GRID.tileWidth / 2;
  const y = point.y - COMMONS_GRID.tileHeight / 2;
  graphics.lineStyle(options.lineWidth || 1, options.lineColor || 0xedb36d, options.alpha ?? 0.42);
  graphics.fillStyle(options.fillColor || 0xedb36d, options.fillAlpha ?? 0.12);
  graphics.fillRect(x, y, COMMONS_GRID.tileWidth, COMMONS_GRID.tileHeight);
  graphics.strokeRect(x, y, COMMONS_GRID.tileWidth, COMMONS_GRID.tileHeight);
}

function interactionHitArea(Phaser, sprite, entity) {
  const hitbox = getCommonsHitbox(entity.asset, entity.entityType);
  return new Phaser.Geom.Rectangle(
    sprite.width * hitbox.x,
    sprite.height * hitbox.y,
    sprite.width * hitbox.width,
    sprite.height * hitbox.height,
  );
}

export function createCommonsPhaserGame({
  Phaser,
  parent,
  initialScene,
  callbacks = {},
  motionPolicy: initialMotionPolicy = {},
}) {
  const interactive = callbacks.interactive === true;
  const inspector = callbacks.inspector === true;

  class Scene extends Phaser.Scene {
    constructor() {
      super({ key: 'CommonsTileScene' });
      this.sprites = new Map();
      this.objectEffects = new Map();
      this.movementTweens = new Map();
      this.floorLayer = null;
      this.gridGuide = null;
      this.targetOverlay = null;
      this.pathOverlay = null;
      this.tileOverlay = null;
      this.tileReadout = null;
      this.drag = null;
      this.objectPointerDown = false;
      this.targetTile = null;
      this.hoverTileKey = null;
      this.pathPreviewKey = null;
      this.currentScene = null;
      this.currentEntities = [];
      this.depthRanks = new Map();
      this.ambientValid = false;
      this.presentationClock = createPresentationClock();
      this.clockUncertaintyMs = 0;
      this.motionPolicy = {
        paused: false,
        reducedMotion: false,
        hidden: false,
        animate: true,
        ...initialMotionPolicy,
      };
    }

    preload() {
      const reportedAssetErrors = new Set();
      this.load.on('loaderror', (file) => {
        const key = file?.key || file?.src || 'unknown-asset';
        if (reportedAssetErrors.has(key)) return;
        reportedAssetErrors.add(key);
        callbacks.onAssetError?.(key);
      });
      this.load.image('commons-room-base', ROOM_ASSET);
      if (inspector) {
        this.load.spritesheet('commons-floor-atlas', FLOOR_ATLAS, {
          frameWidth: 256,
          frameHeight: 256,
        });
      }
      Object.entries(COMMONS_ASSETS).forEach(([asset, path]) => {
        this.load.image(`asset-${asset}`, path);
      });
      Object.entries(COMMONS_ACTOR_ANIMATIONS).forEach(([asset, animation]) => {
        this.load.spritesheet(actorAnimationTextureKey(asset), animation.path, {
          frameWidth: animation.frameWidth,
          frameHeight: animation.frameHeight,
        });
      });
      const queuedStaticTextures = new Set();
      entitiesFromScene(initialScene).forEach((entity) => {
        if (entity.entityType === 'actor' && getCommonsActorAnimation(entity.asset)) return;
        ['south', 'north'].forEach((orientation) => {
          const path = getCommonsAsset(entity.asset, orientation);
          const textureKey = staticAssetTextureKey(entity.asset, orientation);
          if (path && !this.textures.exists(textureKey) && !queuedStaticTextures.has(textureKey)) {
            queuedStaticTextures.add(textureKey);
            this.load.image(textureKey, path);
          }
        });
      });
    }

    create() {
      const stopObservingViewport = observeCommonsViewport({
        parent, scale: this.scale, camera: this.cameras.main,
      });
      this.events.once('shutdown', stopObservingViewport);
      Object.entries(COMMONS_ACTOR_ANIMATIONS).forEach(([asset, animation]) => {
        this.anims.create({
          key: actorAnimationKey(asset),
          frames: this.anims.generateFrameNumbers(actorAnimationTextureKey(asset), {
            start: 0,
            end: animation.frames - 1,
          }),
          frameRate: animation.frameRate,
          repeat: -1,
        });
      });
      this.room = this.add.image(ROOM_WIDTH / 2, ROOM_HEIGHT / 2, 'commons-room-base')
        .setDisplaySize(ROOM_WIDTH, ROOM_HEIGHT)
        .setDepth(-1000);
      this.buildFloorTiles();
      this.tileOverlay = this.add.graphics().setDepth(10000).setVisible(inspector);
      this.targetOverlay = this.add.graphics().setDepth(10001).setVisible(inspector);
      this.pathOverlay = this.add.graphics().setDepth(9998).setVisible(inspector);
      this.gridGuide = this.add.graphics().setDepth(9999).setVisible(false);
      if (inspector) {
        this.tileReadout = this.add.text(12, 12, '', {
          color: '#f3e4c9',
          backgroundColor: '#1b1322cc',
          fontFamily: 'monospace',
          fontSize: '9px',
          padding: { left: 6, right: 6, top: 4, bottom: 4 },
        }).setDepth(10002).setVisible(false);
      }
      if (interactive) this.bindInput();
      this.snapshotTransition = createSnapshotTransition({
        prepare: async (candidate) => {
          await this.prepareSnapshot(candidate);
          this.presentationClock.observe({
            serverTimeMs: Number(candidate.server_time_ms),
            midpointMs: candidate.__client_timing?.midpoint_ms ?? Date.now(),
            uncertaintyMs: candidate.__client_timing?.uncertainty_ms ?? 0,
          });
        },
        needsCorrection: () => Boolean(this.presentationClock.getPendingCorrection()),
        shouldFade: (candidate, current) => {
          const currentAmbient = current?.state?.ambient;
          const nextAmbient = candidate?.state?.ambient;
          const ambientChanged = currentAmbient?.enabled === true
            && nextAmbient?.enabled === true
            && currentAmbient.revision !== nextAmbient.revision;
          return Boolean(ambientChanged || this.presentationClock.getPendingCorrection());
        },
        install: (candidate) => this.installState(candidate),
        fade: (alpha) => this.fadeSnapshot(alpha),
        cancelFade: () => this.cancelSnapshotFade(),
        onError: (error) => callbacks.onAssetError?.(error.message),
      });
      this.snapshotTransition.setPolicy(this.motionPolicy);
      this.events.once('shutdown', () => {
        this.snapshotTransition.dispose();
        this.cancelSnapshotLoad?.();
      });
      this.syncState(initialScene);
    }

    bindInput() {
      this.input.mouse?.disableContextMenu();
      this.input.on('pointermove', (pointer) => {
        const tile = pixelToTile(pointer.worldX, pointer.worldY);
        const nextHoverTileKey = tileKey(tile.tile_x, tile.tile_y);
        if (!this.drag && this.hoverTileKey === nextHoverTileKey) return;
        this.hoverTileKey = nextHoverTileKey;
        this.updateTileReadout(tile);
        if (this.drag) {
          this.pathOverlay?.clear();
          this.drag.moved = this.drag.moved || nextHoverTileKey !== this.drag.startKey;
          const sprite = this.sprites.get(`object:${this.drag.objectId}`);
          if (sprite) this.placeSprite(sprite, tile.tile_x, tile.tile_y);
        }
        this.drawTileOverlay(tile, !isTileAvailable(this.currentScene?.state, tile, {
          entityType: this.drag ? 'object' : 'actor',
          entityId: this.drag?.objectId || 'host',
        }));
      });
      this.input.on('pointerdown', (pointer) => {
        if (pointer.button !== 0 || this.drag || this.objectPointerDown) return;
        const tile = pixelToTile(pointer.worldX, pointer.worldY);
        if (!isTileAvailable(this.currentScene?.state, tile, { entityType: 'actor', entityId: 'host' })) {
          callbacks.onBlockedTile?.();
          return;
        }
        callbacks.onWalkTile?.(tile);
      });
      const finishObjectDrag = (pointer, canCommit = true) => {
        if (!this.drag) return;
        const drag = this.drag;
        const tile = pixelToTile(pointer.worldX, pointer.worldY);
        this.drag = null;
        this.objectPointerDown = false;
        if (drag.moved && canCommit) {
          const available = isTileAvailable(this.currentScene?.state, tile, {
            entityType: 'object',
            entityId: drag.objectId,
          });
          if (available) callbacks.onObjectDrop?.(drag.objectId, tile);
          else {
            const sprite = this.sprites.get(`object:${drag.objectId}`);
            if (sprite) this.placeSprite(sprite, drag.startTile.tile_x, drag.startTile.tile_y);
            callbacks.onInvalidObjectDrop?.();
          }
        } else {
          const sprite = this.sprites.get(`object:${drag.objectId}`);
          if (sprite) this.placeSprite(sprite, drag.startTile.tile_x, drag.startTile.tile_y);
          if (drag.moved && canCommit) callbacks.onInvalidObjectDrop?.();
          else if (canCommit) callbacks.onObjectClick?.(drag.objectId);
        }
      };
      this.input.on('pointerup', (pointer) => finishObjectDrag(pointer, true));
      this.input.on('pointerupoutside', (pointer) => finishObjectDrag(pointer, false));
      this.input.keyboard?.on('keydown', (event) => {
        const key = String(event.key || '').toLowerCase();
        const delta = {
          arrowup: { tile_x: 0, tile_y: -1 },
          w: { tile_x: 0, tile_y: -1 },
          arrowdown: { tile_x: 0, tile_y: 1 },
          s: { tile_x: 0, tile_y: 1 },
          arrowleft: { tile_x: -1, tile_y: 0 },
          a: { tile_x: -1, tile_y: 0 },
          arrowright: { tile_x: 1, tile_y: 0 },
          d: { tile_x: 1, tile_y: 0 },
        }[key];
        if (key === 'escape') {
          this.drag = null;
          this.objectPointerDown = false;
          callbacks.onCancelInteraction?.();
          return;
        }
        if (!delta || this.motionPolicy.paused || this.motionPolicy.stale) return;
        event.preventDefault?.();
        callbacks.onWalkDirection?.(delta);
      });
    }

    update() {
      if (this.snapshotTransition?.isTransitioning() || !this.motionPolicy.animate || !this.currentScene || !this.ambientValid) return;
      const ambient = this.currentScene.state?.ambient;
      if (ambient?.enabled !== true) return;
      const now = this.presentationClock.now();
      this.currentEntities
        .filter((entity) => entity.entityType === 'actor')
        .forEach((actor) => {
          const sprite = this.sprites.get(`actor:${actor.id}`);
          if (!sprite) return;
          const pose = this.clockUncertaintyMs > 500
            ? settleAmbientPose(ambient, actor.id, now, entityTile(actor))
            : evaluateAmbientPose(ambient, actor.id, now, entityTile(actor));
          this.placeContinuousSprite(sprite, pose.u, pose.v);
          this.applyActorPose(sprite, pose);
        });
    }

    setMotionPolicy(nextPolicy = {}) {
      const merged = {
        ...this.motionPolicy,
        ...nextPolicy,
      };
      merged.animate = nextPolicy.animate
        ?? !(merged.paused || merged.reducedMotion || merged.hidden || merged.stale);
      this.motionPolicy = merged;
      this.snapshotTransition?.setPolicy(merged);
      if (this.motionPolicy.paused || this.motionPolicy.hidden) return;
      if (this.motionPolicy.reducedMotion) this.renderHomePoses();
      else if (this.motionPolicy.stale) this.renderStalePoses();
    }

    renderHomePoses() {
      this.stopMovementTweens();
      this.currentEntities
        .filter((entity) => entity.entityType === 'actor')
        .forEach((actor) => {
          const sprite = this.sprites.get(`actor:${actor.id}`);
          if (!sprite) return;
          const tile = entityTile(actor);
          this.placeContinuousSprite(sprite, tile.tile_x, tile.tile_y);
          this.applyActorPose(sprite, {
            mode: 'home',
            progress: 0,
            facing: homeFacing(actor),
          });
        });
    }

    updateTileReadout(tile) {
      if (!this.tileReadout) return;
      const host = this.currentEntities.find((entity) => entity.entityType === 'actor' && entity.id === 'host');
      const hostTile = host ? entityTile(host) : null;
      const distance = hostTile ? ` · ${tileDistance(tile, hostTile)} tiles from host` : '';
      const text = `tile ${tile.tile_x},${tile.tile_y}${distance}`;
      if (this.tileReadout.text !== text) this.tileReadout.setText(text);
      this.tileReadout.setVisible(true);
    }

    drawGridGuide() {
      if (!this.gridGuide) return;
      this.gridGuide.clear();
      const blocked = new Set(
        (this.currentScene?.state?.grid?.blocked || [])
          .filter((entry) => Array.isArray(entry) && entry.length === 2)
          .map(([tileX, tileY]) => tileKey(tileX, tileY)),
      );
      for (let tileY = 0; tileY < COMMONS_GRID.rows; tileY += 1) {
        for (let tileX = 0; tileX < COMMONS_GRID.columns; tileX += 1) {
          const isBlocked = blocked.has(tileKey(tileX, tileY));
          drawDiamond(this.gridGuide, tileX, tileY, {
            lineColor: isBlocked ? 0xd86c68 : 0xf3e4c9,
            lineWidth: isBlocked ? 1.5 : 1,
            alpha: isBlocked ? 0.9 : 0.24,
            fillColor: isBlocked ? 0xd86c68 : 0xf3e4c9,
            fillAlpha: isBlocked ? 0.18 : 0.025,
          });
        }
      }
    }

    toggleGridGuide() {
      if (!inspector || !this.gridGuide) return false;
      const visible = !this.gridGuide.visible;
      this.gridGuide.setVisible(visible);
      if (visible) this.drawGridGuide();
      return visible;
    }

    buildFloorTiles() {
      this.floorLayer?.destroy();
      this.floorLayer = this.add.graphics().setDepth(-950);
      for (let tileY = 0; tileY < COMMONS_GRID.rows; tileY += 1) {
        for (let tileX = 0; tileX < COMMONS_GRID.columns; tileX += 1) {
          const point = projectGround(tileX, tileY);
          const x = point.x - COMMONS_GRID.tileWidth / 2;
          const y = point.y - COMMONS_GRID.tileHeight / 2;
          const alternate = (tileX + tileY) % 2 === 0;
          this.floorLayer.fillStyle(alternate ? 0xf1bf74 : 0xb97355, 0.025);
          this.floorLayer.fillRect(x, y, COMMONS_GRID.tileWidth, COMMONS_GRID.tileHeight);
          this.floorLayer.lineStyle(1, 0x3a2530, 0.14);
          this.floorLayer.strokeRect(x, y, COMMONS_GRID.tileWidth, COMMONS_GRID.tileHeight);
        }
      }
    }

    beginObjectDrag(objectId) {
      const entity = this.currentEntities.find((item) => item.id === objectId);
      if (!entity?.movable) return;
      this.objectPointerDown = true;
      const startTile = entityTile(entity);
      this.drag = {
        objectId,
        startTile,
        startKey: tileKey(startTile.tile_x, startTile.tile_y),
        moved: false,
      };
    }

    placeSprite(sprite, tileX, tileY) {
      this.placeContinuousSprite(sprite, tileX, tileY);
    }

    placeContinuousSprite(sprite, u, v) {
      const point = projectGround(u, v);
      sprite.setPosition(point.x, point.y);
      sprite.setData('groundU', u);
      sprite.setData('groundV', v);
      sprite.setData('positioned', true);
      this.updateSpriteDepth(sprite);
    }

    updateSpriteDepth(sprite) {
      const metadata = sprite.getData('renderMetadata') || {};
      const u = sprite.getData('groundU');
      const v = sprite.getData('groundV');
      if (metadata.floorDecoration) {
        sprite.setDepth(-800 + (Number.isFinite(v) && Number.isFinite(u) ? (u + v) / 10000 : 0));
        return;
      }
      const depth = Number.isFinite(u) && Number.isFinite(v)
        ? depthForGround(u, v, supportDepthOffset(metadata))
        : sprite.y;
      const depthRank = sprite.getData('depthRank');
      sprite.setDepth(depth + (Number.isFinite(depthRank) ? depthRank / 1_000_000 : 0));
    }

    drawTileOverlay(tile, invalid = false) {
      if (!this.tileOverlay?.visible) return;
      this.tileOverlay.clear();
      const draggedEntity = this.drag
        ? this.currentEntities.find((entity) => entity.id === this.drag.objectId)
        : null;
      const footprint = draggedEntity ? getEntityFootprint(draggedEntity) : { cells: [[0, 0]] };
      footprint.cells.forEach(([offsetX, offsetY]) => {
        drawDiamond(this.tileOverlay, tile.tile_x + offsetX, tile.tile_y + offsetY, {
          lineColor: invalid ? 0xd86c68 : 0xedb36d,
          lineWidth: draggedEntity ? 1.5 : 1,
          alpha: invalid ? 0.84 : 0.62,
          fillColor: invalid ? 0xd86c68 : 0xedb36d,
          fillAlpha: draggedEntity ? 0.2 : 0.12,
        });
      });
    }

    renderStalePoses() {
      this.stopMovementTweens();
      const ambient = this.currentScene?.state?.ambient;
      const now = this.presentationClock.now();
      this.currentEntities
        .filter((entity) => entity.entityType === 'actor')
        .forEach((actor) => {
          const sprite = this.sprites.get(`actor:${actor.id}`);
          if (!sprite) return;
          const tile = entityTile(actor);
          const pose = this.ambientValid
            ? settleAmbientPose(ambient, actor.id, now, tile)
            : { mode: 'home', progress: 0, facing: homeFacing(actor) };
          this.placeContinuousSprite(sprite, pose.u ?? tile.tile_x, pose.v ?? tile.tile_y);
          this.applyActorPose(sprite, pose);
        });
    }

    drawTarget(tile) {
      this.targetTile = tile ? normalizeTile(tile.tile_x, tile.tile_y) : null;
      this.pathOverlay?.clear();
      if (!this.targetOverlay?.visible) return;
      this.targetOverlay.clear();
      if (!this.targetTile) return;
      const point = projectGround(this.targetTile.tile_x, this.targetTile.tile_y);
      this.targetOverlay.lineStyle(2, 0xedb36d, 0.9);
      this.targetOverlay.strokeRect(
        point.x - COMMONS_GRID.tileWidth / 2 + 3,
        point.y - COMMONS_GRID.tileHeight / 2 + 3,
        COMMONS_GRID.tileWidth - 6,
        COMMONS_GRID.tileHeight - 6,
      );
      this.targetOverlay.setAlpha(1);
      this.tweens.add({ targets: this.targetOverlay, alpha: 0, duration: 900, ease: 'Cubic.easeOut' });
    }

    async prepareSnapshot(candidate) {
      const validation = validateCommonsSnapshotCandidate(candidate);
      if (!validation.valid) throw new Error(validation.error);
      const requests = getCommonsSnapshotTextureRequests(candidate);
      const missing = requests.filter(({ key }) => !this.textures.exists(key));
      if (!missing.length) return;
      await new Promise((resolve, reject) => {
        const finish = () => {
          cleanup();
          const failed = requests.find(({ key }) => !this.textures.exists(key));
          if (failed) reject(new Error(`Missing scene texture: ${failed.key}`));
          else resolve();
        };
        const cleanup = () => {
          this.load.off('complete', finish);
          this.cancelSnapshotLoad = null;
        };
        this.cancelSnapshotLoad = () => { cleanup(); reject(new Error('Scene disposed')); };
        this.load.once('complete', finish);
        for (const request of missing) {
          if (request.kind === 'spritesheet') this.load.spritesheet(request.key, request.path, {
            frameWidth: request.frameWidth, frameHeight: request.frameHeight,
          });
          else this.load.image(request.key, request.path);
        }
        this.load.start();
      });
    }

    fadeSnapshot(alpha) {
      return new Promise((resolve) => {
        this.finishSnapshotFade = resolve;
        this.snapshotFade = this.tweens.add({
          targets: this.cameras.main, alpha, duration: COMMONS_SNAPSHOT_FADE_MS,
          onComplete: () => { this.finishSnapshotFade = null; this.snapshotFade = null; resolve(); },
        });
      });
    }

    cancelSnapshotFade() {
      this.snapshotFade?.stop();
      this.snapshotFade = null;
      this.finishSnapshotFade?.();
      this.finishSnapshotFade = null;
      this.cameras.main.setAlpha(1);
    }

    syncState(nextScene) {
      if (validateCommonsSnapshotCandidate(nextScene).valid) this.snapshotTransition?.submit(nextScene);
    }

    installState(nextScene) {
      if (!nextScene || !this.textures.exists('commons-room-base')) return;
      if (this.motionPolicy.paused && this.currentScene) return;
      const previousScene = this.currentScene;
      const previousActorTiles = new Map(
        Object.values(previousScene?.state?.actors || {}).map((actor) => [actor.id, entityTile(actor)]),
      );
      this.currentScene = nextScene;
      this.currentEntities = entitiesFromScene(nextScene);
      this.depthRanks = new Map(
        this.currentEntities.map((entity, index) => [`${entity.entityType}:${entity.id}`, index]),
      );
      this.pathPreviewKey = null;
      this.hoverTileKey = null;
      this.presentationClock.reanchor();
      this.clockUncertaintyMs = Number.isFinite(Number(nextScene.__client_timing?.uncertainty_ms))
        ? Number(nextScene.__client_timing.uncertainty_ms)
        : 0;
      const ambient = nextScene.state?.ambient;
      const actorIds = this.currentEntities
        .filter((entity) => entity.entityType === 'actor')
        .map((entity) => entity.id);
      this.ambientValid = Boolean(ambient && validateAmbientProgram(ambient, actorIds).valid);
      if (this.gridGuide?.visible) this.drawGridGuide();

      const currentIds = new Set(this.currentEntities.map((entity) => `${entity.entityType}:${entity.id}`));
      this.sprites.forEach((sprite, id) => {
        if (!currentIds.has(id)) {
          sprite.destroy();
          this.sprites.delete(id);
          this.removeObjectEffect(id);
        }
      });

      this.currentEntities.forEach((entity) => {
        const id = `${entity.entityType}:${entity.id}`;
        const animation = entity.entityType === 'actor' ? getCommonsActorAnimation(entity.asset) : null;
        const orientation = entity.orientation || entity.facing || 'south';
        const requestedTextureKey = animation
          ? actorAnimationTextureKey(entity.asset)
          : staticAssetTextureKey(entity.asset, orientation);
        const fallbackTextureKey = animation
          ? requestedTextureKey
          : staticAssetTextureKey(entity.asset, 'south');
        const textureKey = this.textures.exists(requestedTextureKey)
          ? requestedTextureKey
          : fallbackTextureKey;
        if (!this.textures.exists(textureKey)) return;
        let sprite = this.sprites.get(id);
        if (!sprite) {
          sprite = animation
            ? this.add.sprite(0, 0, textureKey, 0)
            : this.add.image(0, 0, textureKey);
          sprite.setData('entityType', entity.entityType);
          sprite.setData('actorAsset', entity.asset);
          sprite.setData('walkAnimation', animation ? actorAnimationKey(entity.asset) : null);
          this.sprites.set(id, sprite);
          if (interactive && entity.entityType === 'object' && entity.movable) {
            sprite.setInteractive(
              interactionHitArea(Phaser, sprite, entity),
              Phaser.Geom.Rectangle.Contains,
            );
            sprite.input.cursor = 'grab';
            sprite.on('pointerdown', (pointer, _localX, _localY, event) => {
              pointer.event?.stopPropagation?.();
              event?.stopPropagation?.();
              if (pointer.button === 2) callbacks.onObjectRotate?.(entity.id);
              else this.beginObjectDrag(entity.id);
            });
          }
        } else if (!animation && sprite.texture.key !== textureKey) {
          sprite.setTexture(textureKey);
        }
        sprite.setData('depthRank', this.depthRanks.get(id) ?? 0);
        if (entity.entityType === 'actor') sprite.setTint?.(getCommonsActorTint(entity.asset));

        const metadata = getCommonsRenderMetadata(entity.asset, orientation);
        const sourceWidth = Math.max(1, sprite.width);
        const sourceHeight = Math.max(1, sprite.height);
        sprite.setOrigin(...metadata.anchor);
        const displayHeight = Number.isFinite(metadata.height)
          ? metadata.height
          : metadata.width * (sourceHeight / sourceWidth);
        sprite.setDisplaySize(metadata.width, displayHeight);
        if (entity.entityType === 'object') {
          sprite.setFlipX(shouldMirrorCommonsAsset(entity.asset, orientation));
        }
        sprite.setData('renderMetadata', metadata);
        sprite.setAlpha(entity.state?.playing === false || entity.state?.on === false ? 0.72 : 1);
        const tile = entityTile(entity);
        const ambientCanDrive = entity.entityType === 'actor'
          && this.ambientValid
          && ambient?.enabled === true
          && this.motionPolicy.animate
          && !this.motionPolicy.reducedMotion;
        if (entity.entityType === 'actor' && ambientCanDrive) {
          const pose = this.clockUncertaintyMs > 500
            ? settleAmbientPose(ambient, entity.id, this.presentationClock.now(), tile)
            : evaluateAmbientPose(ambient, entity.id, this.presentationClock.now(), tile);
          this.placeContinuousSprite(sprite, pose.u, pose.v);
          this.applyActorPose(sprite, pose);
        } else if (!(this.motionPolicy.paused && sprite.getData('positioned'))) {
          const previousTile = previousActorTiles.get(entity.id);
          const moved = entity.entityType === 'actor'
            && previousTile
            && (previousTile.tile_x !== tile.tile_x || previousTile.tile_y !== tile.tile_y);
          if (moved && this.motionPolicy.animate && !this.motionPolicy.reducedMotion) {
            this.tweenActorToTile(sprite, previousTile, tile, homeFacing(entity));
          } else {
            this.stopMovementTween(sprite);
            this.placeContinuousSprite(sprite, tile.tile_x, tile.tile_y);
            if (entity.entityType === 'actor') {
              this.applyActorPose(sprite, { mode: 'home', progress: 0, facing: homeFacing(entity) });
            }
          }
        }
        if (entity.entityType === 'object') this.syncObjectEffect(entity, tile);
      });
      if (this.motionPolicy.paused || this.motionPolicy.hidden) return;
      if (this.motionPolicy.reducedMotion) this.renderHomePoses();
      else if (this.motionPolicy.stale) this.renderStalePoses();
    }

    applyActorPose(sprite, pose) {
      const animationAsset = sprite.getData('walkAnimation');
      if (!animationAsset) return;
      const asset = sprite.getData('actorAsset');
      const animation = COMMONS_ACTOR_ANIMATIONS[asset];
      const frameCount = 4;
      const directionRow = animation?.directionRows?.[pose.facing || 'front'] ?? 3;
      const frame = directionRow * frameCount + (pose.mode === 'walk'
        ? Math.min(frameCount - 1, Math.floor((pose.progress || 0) * frameCount))
        : 0);
      sprite.anims?.stop();
      sprite.setFrame?.(frame);
      const facing = pose.facing || 'front';
      sprite.setFlipX(isLeftFacing(facing));
      sprite.setData('facing', facing);
      sprite.setData('ambientMode', pose.mode);
    }

    stopMovementTween(sprite) {
      const tween = this.movementTweens.get(sprite);
      if (!tween) return;
      tween.stop();
      this.movementTweens.delete(sprite);
    }

    stopMovementTweens() {
      this.movementTweens.forEach((tween) => tween.stop());
      this.movementTweens.clear();
    }

    tweenActorToTile(sprite, from, to, arrivalFacing) {
      this.stopMovementTween(sprite);
      const deltaU = to.tile_x - from.tile_x;
      const deltaV = to.tile_y - from.tile_y;
      const facing = directionForDelta(deltaU, deltaV) || arrivalFacing || 'front';
      const position = { u: from.tile_x, v: from.tile_y, progress: 0 };
      const tween = this.tweens.add({
        targets: position,
        u: to.tile_x,
        v: to.tile_y,
        progress: 1,
        duration: 180,
        ease: 'Linear',
        onUpdate: () => {
          this.placeContinuousSprite(sprite, position.u, position.v);
          this.applyActorPose(sprite, { mode: 'walk', progress: position.progress, facing });
        },
        onComplete: () => {
          this.movementTweens.delete(sprite);
          this.placeContinuousSprite(sprite, to.tile_x, to.tile_y);
          this.applyActorPose(sprite, { mode: 'home', progress: 0, facing: arrivalFacing || facing });
        },
      });
      this.movementTweens.set(sprite, tween);
    }

    syncObjectEffect(entity, tile) {
      const id = `object:${entity.id}`;
      const active = entity.state?.playing === true || entity.state?.on === true;
      if (!active) {
        this.removeObjectEffect(id);
        return;
      }
      const point = projectGround(tile.tile_x, tile.tile_y);
      const color = entity.state?.playing === true ? 0xc990e8 : 0xf6c56f;
      let effect = this.objectEffects.get(id);
      if (!effect) {
        effect = this.add.ellipse(0, 0, 34, 14, color, 0.16);
        this.objectEffects.set(id, effect);
      }
      effect.setFillStyle?.(color, 0.16);
      effect.setPosition(point.x, point.y - 8);
      effect.setDepth(-700);
    }

    removeObjectEffect(id) {
      const effect = this.objectEffects.get(id);
      if (!effect) return;
      effect.destroy();
      this.objectEffects.delete(id);
    }
  }

  const game = new Phaser.Game({
    type: Phaser.AUTO,
    parent,
    width: ROOM_WIDTH,
    height: ROOM_HEIGHT,
    transparent: true,
    pixelArt: true,
    antialias: false,
    roundPixels: true,
    scale: {
      mode: Phaser.Scale.FIT,
      autoCenter: Phaser.Scale.CENTER_BOTH,
      width: ROOM_WIDTH,
      height: ROOM_HEIGHT,
    },
    scene: Scene,
    render: { antialias: false, pixelArt: true, roundPixels: true },
  });

  game.syncState = (nextScene) => game.scene.getScene('CommonsTileScene')?.syncState(nextScene);
  game.setMotionPolicy = (policy) => game.scene.getScene('CommonsTileScene')?.setMotionPolicy(policy);
  game.drawTarget = (tile) => game.scene.getScene('CommonsTileScene')?.drawTarget(tile);
  game.toggleGrid = () => game.scene.getScene('CommonsTileScene')?.toggleGridGuide();
  return game;
}
