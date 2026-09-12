import { COMMONS_PLAYER_COMPOSITIONS, getCommonsPlayerComposition } from './player-compositions.js';

export { COMMONS_PLAYER_COMPOSITIONS, getCommonsPlayerComposition } from './player-compositions.js';

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
  "cozy-bed": "/commons/assets/cozy-bed.svg",
  "cozy-table": "/commons/assets/cozy-table.svg",
  "cozy-chair": "/commons/assets/cozy-chair.svg",
  "cozy-bookcase": "/commons/assets/cozy-bookcase.svg",
  "cozy-fireplace": "/commons/assets/cozy-fireplace.svg",
  "cozy-chest": "/commons/assets/cozy-chest.svg",
  "cozy-plant": "/commons/assets/cozy-plant.svg",
  host: COMMONS_PLAYER_COMPOSITIONS.host.spritePath,
  maker: COMMONS_PLAYER_COMPOSITIONS.maker.spritePath,
  neighbor: COMMONS_PLAYER_COMPOSITIONS.neighbor.spritePath,
});

export const COMMONS_ACTOR_ANIMATIONS = Object.freeze({
  ...Object.fromEntries(Object.entries(COMMONS_PLAYER_COMPOSITIONS).map(([asset, composition]) => [
    asset,
    Object.freeze({
      path: composition.spritePath,
      frameWidth: composition.frameWidth,
      frameHeight: composition.frameHeight,
      frames: composition.frames,
      frameRate: composition.frameRate,
      directionRows: composition.directionRows,
    }),
  ])),
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

// Logical render widths are authored against the 512-unit world. They keep
// every instance of an asset on the same calibrated mannequin instead of
// deriving size from whichever transparent padding a source PNG happens to
// contain. The legacy percentage API remains below for old inspector callers.
const COMMONS_RENDER_METADATA = Object.freeze({
  "orange-sofa": Object.freeze({
    width: 200, anchor: Object.freeze([0.5, 998 / 1024]), depthOffset: 0,
    sourceSizePx: Object.freeze([1536, 1024]),
    supportPointsPx: Object.freeze([[159, 598], [1021, 998], [1360, 822]].map(Object.freeze)),
  }),
  "green-loveseat": Object.freeze({ width: 138, anchor: Object.freeze([0.5, 987 / 1024]), depthOffset: 0 }),
  "red-armchair": Object.freeze({ width: 108, anchor: Object.freeze([0.5, 1036 / 1254]), depthOffset: 0 }),
  "dining-table": Object.freeze({
    width: 174, anchor: Object.freeze([0.5, 956 / 1024]), depthOffset: 0,
    sourceSizePx: Object.freeze([1536, 1024]),
    supportPointsPx: Object.freeze([[191, 774], [573, 954], [1350, 605]].map(Object.freeze)),
  }),
  "dining-chair": Object.freeze({ width: 72, anchor: Object.freeze([0.5, 1224 / 1295]), depthOffset: 0 }),
  "record-console": Object.freeze({ width: 179, anchor: Object.freeze([0.5, 1022 / 1024]), depthOffset: 0 }),
  "coffee-table": Object.freeze({ width: 92, anchor: Object.freeze([0.5, 871 / 1024]), depthOffset: 0 }),
  "floor-lamp": Object.freeze({ width: 72, anchor: Object.freeze([0.5, 1255 / 1374]), depthOffset: 0 }),
  "area-rug": Object.freeze({ width: 174, anchor: Object.freeze([0.5, 0.5]), depthOffset: -900, floorDecoration: true }),
  topiary: Object.freeze({ width: 66, anchor: Object.freeze([0.5, 1458 / 1536]), depthOffset: 0 }),
  palm: Object.freeze({ width: 97, anchor: Object.freeze([0.5, 1182 / 1297]), depthOffset: 0 }),
  "bar-stool": Object.freeze({ width: 56, anchor: Object.freeze([0.5, 1204 / 1278]), depthOffset: 0 }),
  "cozy-bed": Object.freeze({ width: 92, height: 62, anchor: Object.freeze([0.5, 0.88]), depthOffset: 0 }),
  "cozy-table": Object.freeze({ width: 88, height: 58, anchor: Object.freeze([0.5, 0.9]), depthOffset: 0 }),
  "cozy-chair": Object.freeze({ width: 44, height: 44, anchor: Object.freeze([0.5, 0.91]), depthOffset: 0 }),
  "cozy-bookcase": Object.freeze({ width: 54, height: 70, anchor: Object.freeze([0.5, 0.96]), depthOffset: 0 }),
  "cozy-fireplace": Object.freeze({ width: 72, height: 58, anchor: Object.freeze([0.5, 0.92]), depthOffset: 0 }),
  "cozy-chest": Object.freeze({ width: 58, height: 44, anchor: Object.freeze([0.5, 0.92]), depthOffset: 0 }),
  "cozy-plant": Object.freeze({ width: 42, height: 70, anchor: Object.freeze([0.5, 0.95]), depthOffset: 0 }),
});

// Contact baselines measured in the original source images. Dedicated reverse
// views have different transparent padding and therefore different origins.
const NORTH_RENDER_METADATA = Object.freeze(Object.fromEntries(
  Object.entries({
    "green-loveseat": 988 / 1024,
    "red-armchair": 1060 / 1165,
    "dining-chair": 1226 / 1330,
    "coffee-table": 791 / 1024,
    "floor-lamp": 1310 / 1536,
  }).map(([asset, baseline]) => [asset, Object.freeze({
    ...COMMONS_RENDER_METADATA[asset],
    anchor: Object.freeze([0.5, baseline]),
  })]),
));

const DEFAULT_RENDER_METADATA = Object.freeze({
  width: 82,
  anchor: Object.freeze([0.5, 1]),
  depthOffset: 0,
});

const DEFAULT_OBJECT_HITBOX = Object.freeze({ x: 0.16, y: 0.62, width: 0.68, height: 0.3 });
const ACTOR_HITBOX = Object.freeze({ x: 0.22, y: 0.58, width: 0.56, height: 0.38 });

// Interaction zones stay close to the visible base of each prop. Keeping the
// hit area near the support makes furniture easy to select without stealing
// clicks from neighboring tiles or residents.
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

export function getCommonsRenderMetadata(asset, orientation = "south") {
  const composition = getCommonsPlayerComposition(asset);
  if (composition) {
    return {
      width: composition.displayWidth,
      height: composition.displayHeight,
      anchor: composition.anchor,
      depthOffset: 0,
    };
  }
  if (orientation === "north" && NORTH_RENDER_METADATA[asset]) return NORTH_RENDER_METADATA[asset];
  return COMMONS_RENDER_METADATA[asset] || DEFAULT_RENDER_METADATA;
}

export function getCommonsActorAnimation(asset) {
  return COMMONS_ACTOR_ANIMATIONS[asset] || null;
}

export function getCommonsActorTint(asset) {
  return getCommonsPlayerComposition(asset)?.tint || 0xffffff;
}

export function getCommonsHitbox(asset, entityType = "object") {
  if (entityType === "actor") return ACTOR_HITBOX;
  return COMMONS_HITBOXES[asset] || DEFAULT_OBJECT_HITBOX;
}
