export const COMMONS_ASSETS = Object.freeze({
  "orange-sofa": "/commons/assets/orange-sofa.png",
  "green-loveseat": "/commons/assets/green-loveseat.png",
  "red-armchair": "/commons/assets/red-armchair.png",
  "dining-table": "/commons/assets/dining-table.png",
  "dining-chair": "/commons/assets/dining-chair.png",
  "record-console": "/commons/assets/record-console.png",
  "coffee-table": "/commons/assets/coffee-table.png",
  "floor-lamp": "/commons/assets/floor-lamp.png",
  "area-rug": "/commons/assets/area-rug.png",
  topiary: "/commons/assets/topiary.png",
  palm: "/commons/assets/palm.png",
  "bar-stool": "/commons/assets/bar-stool.png",
  host: "/commons/assets/host.png",
  maker: "/commons/assets/maker.png",
  neighbor: "/commons/assets/neighbor.png",
});

export const COMMONS_ACTOR_ANIMATIONS = Object.freeze({
  host: Object.freeze({
    path: "/commons/assets/host-walk.png", frameWidth: 444, frameHeight: 889, frames: 4, frameRate: 8,
  }),
  maker: Object.freeze({
    path: "/commons/assets/maker-walk.png", frameWidth: 444, frameHeight: 889, frames: 4, frameRate: 8,
  }),
  neighbor: Object.freeze({
    path: "/commons/assets/neighbor-walk.png", frameWidth: 444, frameHeight: 889, frames: 4, frameRate: 8,
  }),
});

const COMMONS_ASSET_ORIENTATIONS = Object.freeze({
  "green-loveseat": Object.freeze({ north: "/commons/assets/green-loveseat-north.png" }),
  "red-armchair": Object.freeze({ north: "/commons/assets/red-armchair-north.png" }),
  "dining-chair": Object.freeze({ north: "/commons/assets/dining-chair-north.png" }),
  "coffee-table": Object.freeze({ north: "/commons/assets/coffee-table-north.png" }),
  "floor-lamp": Object.freeze({ north: "/commons/assets/floor-lamp-north.png" }),
});

const MIRRORED_NORTH_ASSETS = new Set([
  "orange-sofa",
  "dining-table",
  "record-console",
]);

const ASSET_SIZES = Object.freeze({
  "orange-sofa": "39%",
  "green-loveseat": "27%",
  "red-armchair": "21%",
  "dining-table": "34%",
  "dining-chair": "14%",
  "record-console": "35%",
  "coffee-table": "18%",
  "floor-lamp": "14%",
  "area-rug": "34%",
  topiary: "13%",
  palm: "19%",
  "bar-stool": "11%",
  host: "12%",
  maker: "12%",
  neighbor: "12%",
});

const DEFAULT_OBJECT_HITBOX = Object.freeze({ x: 0.16, y: 0.62, width: 0.68, height: 0.3 });
const ACTOR_HITBOX = Object.freeze({ x: 0.22, y: 0.58, width: 0.56, height: 0.38 });

// Interaction zones stay close to the visible base of each prop. The source
// art includes generous transparent padding for isometric overlap, which is
// useful for rendering but makes the default full-texture Phaser hit area
// frustrating when objects sit near one another.
const COMMONS_HITBOXES = Object.freeze({
  "orange-sofa": Object.freeze({ x: 0.08, y: 0.58, width: 0.84, height: 0.34 }),
  "green-loveseat": Object.freeze({ x: 0.1, y: 0.58, width: 0.8, height: 0.34 }),
  "red-armchair": Object.freeze({ x: 0.12, y: 0.58, width: 0.76, height: 0.34 }),
  "dining-table": Object.freeze({ x: 0.06, y: 0.55, width: 0.88, height: 0.38 }),
  "dining-chair": Object.freeze({ x: 0.18, y: 0.58, width: 0.64, height: 0.34 }),
  "record-console": Object.freeze({ x: 0.08, y: 0.54, width: 0.84, height: 0.38 }),
  "coffee-table": Object.freeze({ x: 0.1, y: 0.55, width: 0.8, height: 0.38 }),
  "floor-lamp": Object.freeze({ x: 0.26, y: 0.54, width: 0.48, height: 0.4 }),
  "area-rug": Object.freeze({ x: 0.08, y: 0.24, width: 0.84, height: 0.62 }),
  topiary: Object.freeze({ x: 0.22, y: 0.48, width: 0.56, height: 0.46 }),
  palm: Object.freeze({ x: 0.2, y: 0.46, width: 0.6, height: 0.48 }),
  "bar-stool": Object.freeze({ x: 0.22, y: 0.52, width: 0.56, height: 0.42 }),
});

export function getCommonsAsset(asset, orientation = "south") {
  return COMMONS_ASSET_ORIENTATIONS[asset]?.[orientation] || COMMONS_ASSETS[asset] || null;
}

export function shouldMirrorCommonsAsset(asset, orientation = "south") {
  return orientation === "north"
    && MIRRORED_NORTH_ASSETS.has(asset)
    && !COMMONS_ASSET_ORIENTATIONS[asset]?.north;
}

export function getCommonsAssetSize(asset) {
  return ASSET_SIZES[asset] || "16%";
}

export function getCommonsActorAnimation(asset) {
  return COMMONS_ACTOR_ANIMATIONS[asset] || null;
}

export function getCommonsHitbox(asset, entityType = "object") {
  if (entityType === "actor") return ACTOR_HITBOX;
  return COMMONS_HITBOXES[asset] || DEFAULT_OBJECT_HITBOX;
}
