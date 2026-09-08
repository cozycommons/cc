import {
  COMMONS_ACTOR_ANIMATIONS,
  COMMONS_ASSETS,
  getCommonsActorAnimation,
  getCommonsAsset,
  getCommonsAssetSize,
  getCommonsHitbox,
  shouldMirrorCommonsAsset,
} from './commons-assets.js';
import {
  COMMONS_GRID,
  findTilePath,
  getEntityFootprint,
  isTileAvailable,
  normalizeTile,
  normalizedToTile,
  pixelToTile,
  tileDistance,
  tileKey,
  tileToPixel,
} from './commons-grid.js';

const ROOM_WIDTH = COMMONS_GRID.width;
const ROOM_HEIGHT = COMMONS_GRID.height;
const ROOM_ASSET = '/commons/cozy-commons-room-tile-base.png';
const FLOOR_ATLAS = '/commons/commons-floor-atlas.png';
const AMBIENT_ACTOR_ROUTES = Object.freeze({
  maker: Object.freeze([
    { tile_x: 4, tile_y: 7 },
    { tile_x: 5, tile_y: 8 },
    { tile_x: 4, tile_y: 9 },
    { tile_x: 3, tile_y: 8 },
  ]),
  neighbor: Object.freeze([
    { tile_x: 11, tile_y: 4 },
    { tile_x: 12, tile_y: 5 },
    { tile_x: 11, tile_y: 6 },
    { tile_x: 10, tile_y: 5 },
  ]),
});

function entitiesFromScene(scene) {
  const objects = Object.values(scene?.state?.objects || {}).map((entity) => ({
    ...entity,
    entityType: 'object',
  }));
  const actors = Object.values(scene?.state?.actors || {}).map((entity) => ({
    ...entity,
    entityType: 'actor',
  }));
  return [...objects, ...actors];
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

function percentSize(entity) {
  const raw = getCommonsAssetSize(entity.asset);
  return Number.parseFloat(raw) / 100;
}

function drawDiamond(graphics, tileX, tileY, options = {}) {
  const point = tileToPixel(tileX, tileY);
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
  // Keep the raised edge and woven-rug samples available in the atlas for
  // later room variants; the base room uses the first eight plank tiles.
  return (tileX * 5 + tileY * 3) % 8;
}

function entityDepth(entityType, y) {
  // Actors should win ties with furniture whose anchor lands on the same
  // isometric row. The fractional bias preserves the integer tile ordering.
  return y + (entityType === 'actor' ? 0.5 : 0);
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

export function createCommonsPhaserGame({ Phaser, parent, initialScene, callbacks }) {
  class Scene extends Phaser.Scene {
    constructor() {
      super({ key: 'CommonsTileScene' });
      this.sprites = new Map();
      this.drag = null;
      this.objectPointerDown = false;
      this.hoverTile = null;
      this.targetTile = null;
      this.tileOverlay = null;
      this.targetOverlay = null;
      this.pathOverlay = null;
      this.gridGuide = null;
      this.tileReadout = null;
      this.floorTiles = [];
      this.objectEffects = new Map();
      this.hoverTileKey = null;
      this.pathPreviewKey = null;
      this.localActorWalks = new Map();
      this.ambientActors = new Map();
      this.ambientTimers = new Map();
    }

    preload() {
      this.load.image('commons-room-base', ROOM_ASSET);
      this.load.spritesheet('commons-floor-atlas', FLOOR_ATLAS, {
        frameWidth: 256,
        frameHeight: 256,
      });
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
      const entities = entitiesFromScene(initialScene);
      entities.forEach((entity) => {
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
      this.input.mouse?.disableContextMenu();
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
      this.tileOverlay = this.add.graphics().setDepth(10000);
      this.targetOverlay = this.add.graphics().setDepth(10001);
      this.pathOverlay = this.add.graphics().setDepth(9998);
      this.gridGuide = this.add.graphics().setDepth(9999).setVisible(false);
      this.tileReadout = this.add.text(12, 12, '', {
        color: '#f3e4c9',
        backgroundColor: '#1b1322cc',
        fontFamily: 'monospace',
        fontSize: '9px',
        padding: { left: 6, right: 6, top: 4, bottom: 4 },
      }).setDepth(10002).setVisible(false);

      this.input.on('pointermove', (pointer) => {
        const tile = pixelToTile(pointer.worldX, pointer.worldY);
        const nextHoverTileKey = tileKey(tile.tile_x, tile.tile_y);
        if (!this.drag && this.hoverTileKey === nextHoverTileKey) return;
        this.hoverTileKey = nextHoverTileKey;
        this.hoverTile = tile;
        this.updateTileReadout(tile);
        const invalid = this.drag
          ? !isTileAvailable(this.currentScene?.state, tile, {
            entityType: 'object',
            entityId: this.drag.objectId,
          })
          : !isTileAvailable(this.currentScene?.state, tile, {
            entityType: 'actor',
            entityId: 'host',
          });
        if (this.drag) {
          this.pathOverlay?.clear();
          this.drag.moved = this.drag.moved || tileKey(tile.tile_x, tile.tile_y) !== this.drag.startKey;
          const sprite = this.sprites.get(`object:${this.drag.objectId}`);
          if (sprite) this.placeSprite(sprite, tile.tile_x, tile.tile_y);
        } else {
          this.drawPathPreview(tile);
        }
        this.drawTileOverlay(tile, invalid);
      });

      this.input.on('pointerdown', (pointer) => {
        if (pointer.button !== 0 || this.drag || this.objectPointerDown) return;
        const tile = pixelToTile(pointer.worldX, pointer.worldY);
        this.pathOverlay?.clear();
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
        this.drawTileOverlay(tile, !isTileAvailable(this.currentScene?.state, tile, {
          entityType: 'object',
          entityId: drag.objectId,
        }));
      };

      this.input.on('pointerup', (pointer) => finishObjectDrag(pointer, true));
      this.input.on('pointerupoutside', (pointer) => finishObjectDrag(pointer, false));

      this.syncState(initialScene);
      this.startAmbientActors();
    }

    updateTileReadout(tile) {
      if (!this.tileReadout) return;
      const host = this.currentEntities?.find((entity) => entity.entityType === 'actor' && entity.id === 'host');
      const hostTile = host ? entityTile(host) : null;
      const distance = hostTile ? ` · ${tileDistance(tile, hostTile)} tiles from host` : '';
      const text = `tile ${tile.tile_x},${tile.tile_y}${distance}`;
      if (this.tileReadout.text !== text) this.tileReadout.setText(text);
      this.tileReadout.setVisible(true);
    }

    drawPathPreview(tile) {
      if (!this.pathOverlay) return;
      this.pathOverlay.clear();
      const host = this.currentEntities?.find((entity) => (
        entity.entityType === 'actor' && entity.id === 'host'
      ));
      if (!host || !this.currentScene) return;
      const previewKey = [
        this.currentScene.version,
        tileKey(entityTile(host).tile_x, entityTile(host).tile_y),
        tileKey(tile.tile_x, tile.tile_y),
      ].join('|');
      if (this.pathPreviewKey === previewKey) return;
      this.pathPreviewKey = previewKey;
      const path = findTilePath(
        this.currentScene.state,
        entityTile(host),
        tile,
        { entityType: 'actor', entityId: 'host' },
      );
      path.forEach((step, index) => {
        drawDiamond(this.pathOverlay, step.tile_x, step.tile_y, {
          lineColor: 0x9ad5b1,
          lineWidth: index === path.length - 1 ? 1.5 : 1,
          alpha: 0.48,
          fillColor: 0x9ad5b1,
          fillAlpha: index === path.length - 1 ? 0.16 : 0.08,
        });
      });
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
      if (!this.gridGuide) return false;
      const visible = !this.gridGuide.visible;
      this.gridGuide.setVisible(visible);
      if (visible) this.drawGridGuide();
      return visible;
    }

    buildFloorTiles() {
      for (let tileY = 0; tileY < COMMONS_GRID.rows; tileY += 1) {
        for (let tileX = 0; tileX < COMMONS_GRID.columns; tileX += 1) {
          const point = tileToPixel(tileX, tileY);
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
      const entity = this.currentEntities?.find((item) => item.id === objectId);
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

    placeSprite(sprite, tileX, tileY, { animate = false } = {}) {
      const point = tileToPixel(tileX, tileY);
      const positioned = sprite.getData('positioned') === true;
      if (animate && positioned) {
        this.tweens.killTweensOf(sprite);
        this.tweens.add({
          targets: sprite,
          x: point.x,
          y: point.y,
          duration: 150,
          ease: 'Linear',
          onUpdate: () => this.updateSpriteDepth(sprite),
        });
      } else {
        sprite.setPosition(point.x, point.y);
      }
      this.updateSpriteDepth(sprite, point.y);
      sprite.setData('positioned', true);
    }

    updateSpriteDepth(sprite, y = sprite.y) {
      sprite.setDepth(entityDepth(sprite.getData('entityType'), y));
    }

    drawTileOverlay(tile, invalid = false) {
      if (!this.tileOverlay) return;
      this.tileOverlay.clear();
      const draggedEntity = this.drag
        ? this.currentEntities?.find((entity) => entity.id === this.drag.objectId)
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
      if (this.targetTile) {
        drawDiamond(this.tileOverlay, this.targetTile.tile_x, this.targetTile.tile_y, {
          lineColor: 0xf3e4c9,
          lineWidth: 1,
          alpha: 0.7,
          fillColor: 0xf3e4c9,
          fillAlpha: 0.16,
        });
      }
    }

    drawTarget(tile) {
      this.targetTile = tile ? normalizeTile(tile.tile_x, tile.tile_y) : null;
      this.pathOverlay?.clear();
      this.pathPreviewKey = null;
      if (!this.targetOverlay) return;
      this.targetOverlay.clear();
      if (!this.targetTile) return;
      const point = tileToPixel(this.targetTile.tile_x, this.targetTile.tile_y);
      this.targetOverlay.lineStyle(2, 0xedb36d, 0.9);
      this.targetOverlay.strokeEllipse(point.x, point.y, 22, 10);
      this.targetOverlay.setAlpha(1);
      this.tweens.add({ targets: this.targetOverlay, alpha: 0, duration: 900, ease: 'Cubic.easeOut' });
    }

    syncState(nextScene) {
      if (!nextScene || !this.textures.exists('commons-room-base')) return;
      this.currentScene = nextScene;
      this.currentEntities = entitiesFromScene(nextScene);
      this.pathPreviewKey = null;
      this.hoverTileKey = null;
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
        const animation = entity.entityType === 'actor'
          ? getCommonsActorAnimation(entity.asset)
          : null;
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
            ? this.add.sprite(0, 0, textureKey, 0).setOrigin(0.5, 1)
            : this.add.image(0, 0, textureKey).setOrigin(0.5, 1);
          sprite.setData('baseWidth', sprite.width);
          sprite.setData('walkAnimation', animation ? actorAnimationKey(entity.asset) : null);
          sprite.setData('entityType', entity.entityType);
          this.sprites.set(id, sprite);
          if (entity.entityType === 'object' && entity.movable) {
            sprite.setInteractive(
              interactionHitArea(Phaser, sprite, entity),
              Phaser.Geom.Rectangle.Contains,
            );
            sprite.input.cursor = 'grab';
            sprite.on('pointerdown', (pointer, _localX, _localY, event) => {
              pointer.event?.stopPropagation?.();
              event?.stopPropagation?.();
              if (pointer.button === 2) {
                callbacks.onObjectRotate?.(entity.id);
                return;
              }
              this.beginObjectDrag(entity.id);
            });
          }
        } else if (!animation && sprite.texture.key !== textureKey) {
          sprite.setTexture(textureKey);
          sprite.setData('baseWidth', sprite.width);
        }
        const tile = entityTile(entity);
        const percent = percentSize(entity);
        sprite.setScale((ROOM_WIDTH * percent) / sprite.getData('baseWidth'));
        sprite.setAlpha(entity.state?.playing === false || entity.state?.on === false ? 0.72 : 1);
        const mirrored = entity.entityType === 'actor'
          ? (entity.orientation || entity.facing) === 'west'
          : shouldMirrorCommonsAsset(entity.asset, entity.orientation || entity.facing || 'south');
        sprite.setFlipX(Boolean(mirrored));
        const canonicalTileKey = tileKey(tile.tile_x, tile.tile_y);
        if (entity.entityType === 'actor' && entity.id !== 'host') {
          const ambient = this.ambientActors.get(entity.id);
          if (!ambient || ambient.canonicalKey !== canonicalTileKey) {
            this.ambientActors.set(entity.id, {
              canonicalKey: canonicalTileKey,
              tile,
              routeIndex: 0,
            });
          }
        }
        const ambientActor = entity.entityType === 'actor' && entity.id !== 'host'
          ? this.ambientActors.get(entity.id)
          : null;
        const localWalk = entity.entityType === 'actor' ? this.localActorWalks.get(entity.id) : null;
        const preserveLocalPosition = Boolean(localWalk?.expectedKeys.has(canonicalTileKey));
        const visualTargetMatchesCanonical = entity.entityType === 'actor'
          && sprite.getData('visualTargetKey') === canonicalTileKey;
        const preserveAmbientPosition = Boolean(
          ambientActor && ambientActor.canonicalKey === canonicalTileKey,
        );
        if (!this.drag || this.drag.objectId !== entity.id) {
          if (preserveLocalPosition || visualTargetMatchesCanonical) {
            this.updateSpriteDepth(sprite);
          } else if (preserveAmbientPosition) {
            this.placeSprite(sprite, ambientActor.tile.tile_x, ambientActor.tile.tile_y);
          } else {
            this.placeSprite(sprite, tile.tile_x, tile.tile_y, {
              animate: entity.entityType === 'actor',
            });
          }
        }
        if (entity.entityType === 'object') {
          this.syncObjectEffect(entity, tile);
        }
      });
    }

    syncObjectEffect(entity, tile) {
      const id = `object:${entity.id}`;
      const active = entity.state?.playing === true || entity.state?.on === true;
      const existing = this.objectEffects.get(id);
      if (!active) {
        this.removeObjectEffect(id);
        return;
      }

      const point = tileToPixel(tile.tile_x, tile.tile_y);
      const color = entity.state?.playing === true ? 0xc990e8 : 0xf6c56f;
      let effect = existing;
      if (!effect) {
        effect = this.add.container(0, 0).setDepth(10001);
        const glow = this.add.ellipse(0, 0, 34, 14, color, 0.18);
        const icon = this.add.text(14, -18, entity.state?.playing === true ? '♪' : '✦', {
          color: entity.state?.playing === true ? '#e9c7ff' : '#ffe4a3',
          fontFamily: 'monospace',
          fontSize: '16px',
          stroke: '#241726',
          strokeThickness: 3,
        }).setOrigin(0.5, 0.5);
        effect.add([glow, icon]);
        effect.setData('glow', glow);
        effect.setData('icon', icon);
        this.objectEffects.set(id, effect);
        this.tweens.add({
          targets: glow,
          alpha: 0.05,
          scaleX: 1.2,
          scaleY: 1.2,
          duration: 850,
          ease: 'Sine.easeInOut',
          yoyo: true,
          repeat: -1,
        });
        this.tweens.add({
          targets: icon,
          y: -27,
          alpha: 0.25,
          duration: 1200,
          ease: 'Sine.easeOut',
          yoyo: true,
          repeat: -1,
        });
      }
      effect.setPosition(point.x, point.y - 8).setDepth(point.y + 20);
    }

    removeObjectEffect(id) {
      const effect = this.objectEffects.get(id);
      if (!effect) return;
      effect.list?.forEach((child) => this.tweens.killTweensOf(child));
      effect.removeAll(true);
      effect.destroy();
      this.objectEffects.delete(id);
    }

    startActorAnimation(sprite) {
      const animationKey = sprite.getData('walkAnimation');
      if (animationKey && sprite.anims) {
        sprite.anims.play({ key: animationKey, repeat: -1 }, true);
      }
    }

    startAmbientActors() {
      if (globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches) return;
      Object.keys(AMBIENT_ACTOR_ROUTES).forEach((actorId, index) => {
        this.scheduleAmbientActor(actorId, 1100 + index * 1300);
      });
    }

    scheduleAmbientActor(actorId, delay) {
      const currentTimer = this.ambientTimers.get(actorId);
      currentTimer?.remove?.();
      const timer = this.time.delayedCall(delay, () => this.runAmbientActor(actorId));
      this.ambientTimers.set(actorId, timer);
    }

    runAmbientActor(actorId) {
      const route = AMBIENT_ACTOR_ROUTES[actorId];
      const ambient = this.ambientActors.get(actorId);
      const actor = this.currentEntities?.find((entity) => entity.entityType === 'actor' && entity.id === actorId);
      if (!route || !ambient || !actor || !this.currentScene) return;

      const targetIndex = (ambient.routeIndex + 1) % route.length;
      const pathState = {
        ...this.currentScene.state,
        actors: {
          ...this.currentScene.state.actors,
          [actorId]: {
            ...actor,
            tile_x: ambient.tile.tile_x,
            tile_y: ambient.tile.tile_y,
          },
        },
      };
      const path = findTilePath(
        pathState,
        ambient.tile,
        route[targetIndex],
        { entityType: 'actor', entityId: actorId },
      );
      if (!path.length) {
        this.scheduleAmbientActor(actorId, 1600);
        return;
      }

      ambient.routeIndex = targetIndex;
      this.walkActorPath(actorId, path, { ambient: true });
      this.time.delayedCall(path.length * 180 + 80, () => {
        this.finishActorWalk(actorId, true);
        this.scheduleAmbientActor(actorId, 900 + Phaser.Math.Between(0, 1100));
      });
    }

    stopActorAnimation(sprite) {
      if (!sprite?.active) return;
      sprite.anims?.stop();
      sprite.setFrame?.(0);
    }

    walkActorPath(actorId, path, { ambient = false } = {}) {
      const id = `actor:${actorId}`;
      const sprite = this.sprites.get(id);
      if (!sprite || !path?.length) return;
      this.cancelActorWalk(actorId, { reconcile: false });
      const actor = this.currentEntities?.find((entity) => entity.entityType === 'actor' && entity.id === actorId);
      const ambientActor = ambient ? this.ambientActors.get(actorId) : null;
      const startTile = ambientActor?.tile || (actor ? entityTile(actor) : null);
      const expectedKeys = new Set([
        startTile ? tileKey(startTile.tile_x, startTile.tile_y) : null,
        ...path.map((tile) => tileKey(tile.tile_x, tile.tile_y)),
      ].filter(Boolean));
      const walk = {
        ambient,
        expectedKeys,
        finalTile: path.at(-1),
        startTile,
        tween: null,
        finished: false,
      };
      this.localActorWalks.set(actorId, walk);

      const moveNext = (index) => {
        if (walk.cancelled || index >= path.length) {
          walk.finished = true;
          this.stopActorAnimation(sprite);
          return;
        }
        const tile = path[index];
        const previousTile = index === 0 ? startTile : path[index - 1];
        const point = tileToPixel(tile.tile_x, tile.tile_y);
        sprite.setData('visualTargetKey', tileKey(tile.tile_x, tile.tile_y));
        if (tile.tile_x !== previousTile?.tile_x) sprite.setFlipX(tile.tile_x < previousTile.tile_x);
        this.startActorAnimation(sprite);
        walk.tween = this.tweens.add({
          targets: sprite,
          x: point.x,
          y: point.y,
          duration: 155,
          ease: 'Sine.easeInOut',
          onUpdate: () => this.updateSpriteDepth(sprite),
          onComplete: () => moveNext(index + 1),
        });
      };
      moveNext(0);
    }

    finishActorWalk(actorId, success) {
      const walk = this.localActorWalks.get(actorId);
      if (success) {
        if (walk?.ambient) {
          const ambient = this.ambientActors.get(actorId);
          if (ambient && walk.finalTile) ambient.tile = walk.finalTile;
        }
        this.localActorWalks.delete(actorId);
        return;
      }
      this.cancelActorWalk(actorId, { reconcile: true });
    }

    cancelActorWalk(actorId, { reconcile = true } = {}) {
      const walk = this.localActorWalks.get(actorId);
      const sprite = this.sprites.get(`actor:${actorId}`);
      if (walk) {
        walk.cancelled = true;
        if (sprite) this.tweens.killTweensOf(sprite);
        this.localActorWalks.delete(actorId);
      }
      if (!sprite) return;
      this.stopActorAnimation(sprite);
      sprite.setData('visualTargetKey', null);
      if (reconcile) {
        const ambient = this.ambientActors.get(actorId);
        const entity = this.currentEntities?.find((item) => item.entityType === 'actor' && item.id === actorId);
        const tile = ambient?.tile || (entity ? entityTile(entity) : null);
        if (tile) this.placeSprite(sprite, tile.tile_x, tile.tile_y);
      }
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
  game.drawTarget = (tile) => game.scene.getScene('CommonsTileScene')?.drawTarget(tile);
  game.toggleGrid = () => game.scene.getScene('CommonsTileScene')?.toggleGridGuide();
  game.walkActorPath = (actorId, path, options) => game.scene.getScene('CommonsTileScene')?.walkActorPath(actorId, path, options);
  game.finishActorWalk = (actorId, success) => game.scene.getScene('CommonsTileScene')?.finishActorWalk(actorId, success);
  game.cancelActorWalk = (actorId) => game.scene.getScene('CommonsTileScene')?.cancelActorWalk(actorId);
  return game;
}
