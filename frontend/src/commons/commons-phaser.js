import {
  COMMONS_ACTOR_ANIMATIONS,
  COMMONS_ASSETS,
  getCommonsActorAnimation,
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
import { evaluateAmbientPose, validateAmbientProgram } from './ambient/timeline.js';
import { depthForGround, projectGround } from './world/geometry.js';

const ROOM_WIDTH = COMMONS_GRID.width;
const ROOM_HEIGHT = COMMONS_GRID.height;
const ROOM_ASSET = '/commons/cozy-commons-room-tile-base.png';
const FLOOR_ATLAS = '/commons/commons-floor-atlas.png';

function entitiesFromScene(scene) {
  const objects = Object.values(scene?.state?.objects || {}).map((entity) => ({
    ...entity,
    entityType: 'object',
  }));
  const actors = Object.values(scene?.state?.actors || {}).map((entity) => ({
    ...entity,
    entityType: 'actor',
  }));
  return [...objects, ...actors].filter((entity) => entity.visible !== false && entity.hidden !== true);
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
  if (typeof facing === 'string' && facing.startsWith('front_')) return facing;
  if (typeof facing === 'string' && facing.startsWith('back_')) return facing;
  return {
    north: 'back_right',
    south: 'front_right',
    east: 'front_right',
    west: 'front_left',
  }[facing] || 'front_right';
}

function isLeftFacing(facing) {
  return facing === 'front_left' || facing === 'back_left';
}

function drawDiamond(graphics, tileX, tileY, options = {}) {
  const point = projectGround(tileX, tileY);
  const halfWidth = COMMONS_GRID.tileWidth / 2;
  const halfHeight = COMMONS_GRID.tileHeight / 2;
  graphics.lineStyle(options.lineWidth || 1, options.lineColor || 0xedb36d, options.alpha ?? 0.42);
  graphics.fillStyle(options.fillColor || 0xedb36d, options.fillAlpha ?? 0.12);
  graphics.beginPath();
  graphics.moveTo(point.x, point.y - halfHeight);
  graphics.lineTo(point.x + halfWidth, point.y);
  graphics.lineTo(point.x, point.y + halfHeight);
  graphics.lineTo(point.x - halfWidth, point.y);
  graphics.closePath();
  graphics.fillPath();
  graphics.strokePath();
}

function floorFrame(tileX, tileY) {
  return (tileX * 5 + tileY * 3) % 8;
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
      this.floorTiles = [];
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
      this.ambientValid = false;
      this.clockOffsetMs = 0;
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
      if (inspector) this.buildFloorTiles();
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
    }

    update() {
      if (!this.motionPolicy.animate || !this.currentScene || !this.ambientValid) return;
      const ambient = this.currentScene.state?.ambient;
      const now = Date.now() + this.clockOffsetMs;
      this.currentEntities
        .filter((entity) => entity.entityType === 'actor')
        .forEach((actor) => {
          const sprite = this.sprites.get(`actor:${actor.id}`);
          if (!sprite) return;
          const pose = evaluateAmbientPose(ambient, actor.id, now, entityTile(actor));
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
        ?? !(merged.paused || merged.reducedMotion || merged.hidden);
      this.motionPolicy = merged;
      if (this.motionPolicy.reducedMotion) this.renderHomePoses();
    }

    renderHomePoses() {
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
      for (let tileY = 0; tileY < COMMONS_GRID.rows; tileY += 1) {
        for (let tileX = 0; tileX < COMMONS_GRID.columns; tileX += 1) {
          const point = projectGround(tileX, tileY);
          const tile = this.add.sprite(point.x, point.y, 'commons-floor-atlas', floorFrame(tileX, tileY))
            .setOrigin(0.5, 0.5)
            .setDisplaySize(COMMONS_GRID.tileWidth, COMMONS_GRID.tileHeight + 4)
            .setAlpha(0.46)
            .setDepth(-900 + point.y / 10000);
          this.floorTiles.push(tile);
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
        ? depthForGround(u, v, metadata.depthOffset || 0)
        : sprite.y;
      sprite.setDepth(depth + (sprite.getData('entityType') === 'actor' ? 0.01 : 0));
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

    drawTarget(tile) {
      this.targetTile = tile ? normalizeTile(tile.tile_x, tile.tile_y) : null;
      this.pathOverlay?.clear();
      if (!this.targetOverlay?.visible) return;
      this.targetOverlay.clear();
      if (!this.targetTile) return;
      const point = projectGround(this.targetTile.tile_x, this.targetTile.tile_y);
      this.targetOverlay.lineStyle(2, 0xedb36d, 0.9);
      this.targetOverlay.strokeEllipse(point.x, point.y, 22, 10);
      this.targetOverlay.setAlpha(1);
      this.tweens.add({ targets: this.targetOverlay, alpha: 0, duration: 900, ease: 'Cubic.easeOut' });
    }

    syncState(nextScene) {
      if (!nextScene || !this.textures.exists('commons-room-base')) return;
      if (this.motionPolicy.paused && this.currentScene) return;
      this.currentScene = nextScene;
      this.currentEntities = entitiesFromScene(nextScene);
      this.pathPreviewKey = null;
      this.hoverTileKey = null;
      this.clockOffsetMs = Number.isFinite(Number(nextScene.server_time_ms))
        ? Number(nextScene.server_time_ms) - Date.now()
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

        const metadata = getCommonsRenderMetadata(entity.asset);
        const sourceWidth = Math.max(1, sprite.width);
        const sourceHeight = Math.max(1, sprite.height);
        sprite.setOrigin(...metadata.anchor);
        sprite.setDisplaySize(metadata.width, metadata.width * (sourceHeight / sourceWidth));
        if (entity.entityType === 'object') {
          sprite.setFlipX(shouldMirrorCommonsAsset(entity.asset, orientation));
        }
        sprite.setData('renderMetadata', metadata);
        sprite.setAlpha(entity.state?.playing === false || entity.state?.on === false ? 0.72 : 1);
        const tile = entityTile(entity);
        const ambientCanDrive = entity.entityType === 'actor'
          && this.ambientValid
          && this.motionPolicy.animate
          && !this.motionPolicy.reducedMotion;
        if (entity.entityType === 'actor' && ambientCanDrive) {
          const pose = evaluateAmbientPose(ambient, entity.id, Date.now() + this.clockOffsetMs, tile);
          this.placeContinuousSprite(sprite, pose.u, pose.v);
          this.applyActorPose(sprite, pose);
        } else if (!(this.motionPolicy.paused && sprite.getData('positioned'))) {
          this.placeContinuousSprite(sprite, tile.tile_x, tile.tile_y);
          if (entity.entityType === 'actor') {
            this.applyActorPose(sprite, { mode: 'home', progress: 0, facing: homeFacing(entity) });
          }
        }
        if (entity.entityType === 'object') this.syncObjectEffect(entity, tile);
      });
      if (this.motionPolicy.reducedMotion) this.renderHomePoses();
    }

    applyActorPose(sprite, pose) {
      const animationAsset = sprite.getData('walkAnimation');
      if (!animationAsset) return;
      const animation = COMMONS_ACTOR_ANIMATIONS[sprite.getData('entityType') === 'actor'
        ? sprite.texture.key.replace('actor-animation-', '')
        : ''];
      const frameCount = animation?.frames || 4;
      const frame = pose.mode === 'walk'
        ? Math.min(frameCount - 1, Math.floor((pose.progress || 0) * frameCount))
        : 0;
      sprite.anims?.stop();
      sprite.setFrame?.(frame);
      const facing = pose.facing || 'front_right';
      sprite.setFlipX(isLeftFacing(facing));
      sprite.setData('facing', facing);
      sprite.setData('ambientMode', pose.mode);
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
      effect.setDepth(point.y + 20);
    }

    removeObjectEffect(id) {
      const effect = this.objectEffects.get(id);
      if (!effect) return;
      effect.destroy();
      this.objectEffects.delete(id);
    }
  }

  const dpr = Math.min(Math.max(globalThis.devicePixelRatio || 1, 1), 2);
  const game = new Phaser.Game({
    type: Phaser.AUTO,
    parent,
    width: ROOM_WIDTH,
    height: ROOM_HEIGHT,
    resolution: dpr,
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
