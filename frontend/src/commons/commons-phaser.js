import {
  COMMONS_ACTOR_ANIMATIONS,
  COMMONS_ASSETS,
  getCommonsActorAnimation,
  getCommonsAsset,
  getCommonsAssetSize,
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
  tileToPixel,
} from './commons-grid.js';

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
    }

    updateTileReadout(tile) {
      if (!this.tileReadout) return;
      const host = this.currentEntities?.find((entity) => entity.entityType === 'actor' && entity.id === 'host');
      const hostTile = host ? entityTile(host) : null;
      const distance = hostTile ? ` · ${tileDistance(tile, hostTile)} tiles from host` : '';
      this.tileReadout.setText(`tile ${tile.tile_x},${tile.tile_y}${distance}`).setVisible(true);
    }

    drawPathPreview(tile) {
      if (!this.pathOverlay) return;
      this.pathOverlay.clear();
      const host = this.currentEntities?.find((entity) => (
        entity.entityType === 'actor' && entity.id === 'host'
      ));
      if (!host || !this.currentScene) return;
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
        this.tweens.add({
          targets: sprite,
          x: point.x,
          y: point.y,
          duration: 150,
          ease: 'Linear',
        });
      } else {
        sprite.setPosition(point.x, point.y);
      }
      sprite.setDepth(point.y).setData('positioned', true);
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
          this.sprites.set(id, sprite);
          if (entity.entityType === 'object' && entity.movable) {
            sprite.setInteractive({ useHandCursor: true });
            sprite.on('pointerdown', (pointer) => {
              pointer.event?.stopPropagation?.();
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
        if (!this.drag || this.drag.objectId !== entity.id) {
          this.placeSprite(sprite, tile.tile_x, tile.tile_y, {
            animate: entity.entityType === 'actor',
          });
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
  game.walkingActor = (actorId) => {
    const scene = game.scene.getScene('CommonsTileScene');
    const sprite = scene?.sprites.get(`actor:${actorId}`);
    if (!sprite) return;
    const animationKey = sprite.getData('walkAnimation');
    if (animationKey && sprite.anims) {
      sprite.anims.play({ key: animationKey, repeat: 1 });
      scene.time.delayedCall(1050, () => {
        if (!sprite.active) return;
        sprite.anims.stop();
        sprite.setFrame(0);
      });
    }
    scene.tweens.add({
      targets: sprite,
      angle: sprite.flipX ? -2 : 2,
      duration: 90,
      yoyo: true,
      repeat: 2,
      ease: 'Sine.easeInOut',
    });
  };
  return game;
}
