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
