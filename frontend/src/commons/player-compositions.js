const DIRECTION_ROWS = Object.freeze({ back: 0, left: 1, right: 2, front: 3 });
const SOURCE_PIXEL_SCALE = 2;

// The room has a small cast rather than a single tinted mannequin. Keeping
// the composition data separate from Phaser lets future rooms reuse the same
// silhouettes while swapping clothes, palettes, or accessories.
export const COMMONS_PLAYER_COMPOSITIONS = Object.freeze({
  host: Object.freeze({
    id: 'host',
    displayName: 'Juniper',
    role: 'host',
    spritePath: '/commons/assets/resident-host-walk.svg',
    palette: Object.freeze({ hair: '#7b3f2d', clothing: '#60734a', accent: '#e7c69c' }),
    silhouette: 'auburn bun, moss overalls, tool satchel',
    sourcePixelScale: SOURCE_PIXEL_SCALE,
    displayWidth: 30,
    displayHeight: 46,
    anchor: Object.freeze([0.5, 0.96]),
    tint: 0xffffff,
    frameWidth: 64,
    frameHeight: 96,
    frames: 16,
    frameRate: 8,
    directionRows: DIRECTION_ROWS,
  }),
  maker: Object.freeze({
    id: 'maker',
    displayName: 'Marlow',
    role: 'maker',
    spritePath: '/commons/assets/resident-maker-walk.svg',
    palette: Object.freeze({ hair: '#3d2a32', clothing: '#704554', accent: '#c9b4dc' }),
    silhouette: 'dark bob, plum cardigan, lavender scarf, round glasses',
    sourcePixelScale: SOURCE_PIXEL_SCALE,
    displayWidth: 30,
    displayHeight: 46,
    anchor: Object.freeze([0.5, 0.96]),
    tint: 0xffffff,
    frameWidth: 64,
    frameHeight: 96,
    frames: 16,
    frameRate: 8,
    directionRows: DIRECTION_ROWS,
  }),
  neighbor: Object.freeze({
    id: 'neighbor',
    displayName: 'Pip',
    role: 'neighbor',
    spritePath: '/commons/assets/resident-neighbor-walk.svg',
    palette: Object.freeze({ hair: '#4a3029', clothing: '#d69a4f', accent: '#3f7880' }),
    silhouette: 'short tousled hair, honey sweater, teal trousers, rust satchel',
    sourcePixelScale: SOURCE_PIXEL_SCALE,
    displayWidth: 30,
    displayHeight: 46,
    anchor: Object.freeze([0.5, 0.96]),
    tint: 0xffffff,
    frameWidth: 64,
    frameHeight: 96,
    frames: 16,
    frameRate: 8,
    directionRows: DIRECTION_ROWS,
  }),
});

export function getCommonsPlayerComposition(asset) {
  return COMMONS_PLAYER_COMPOSITIONS[asset] || null;
}
