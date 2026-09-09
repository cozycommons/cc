export const COMMONS_WORLD = Object.freeze({
  columns: 16,
  rows: 16,
  width: 512,
  height: 512,
  tileWidth: 32,
  tileHeight: 20,
  originX: 256,
  originY: 180,
  sourceScale: 3,
});

export const COMMONS_DIRECTION_BY_DELTA = Object.freeze({
  '1,0': 'front_right',
  '-1,0': 'back_left',
  '0,1': 'front_left',
  '0,-1': 'back_right',
});

export const COMMONS_FLOOR_BOUNDARY = Object.freeze([
  Object.freeze({ u: -0.5, v: -0.5 }),
  Object.freeze({ u: 15.5, v: -0.5 }),
  Object.freeze({ u: 15.5, v: 15.5 }),
  Object.freeze({ u: -0.5, v: 15.5 }),
]);

function finite(value, name) {
  if (typeof value !== 'number' || !Number.isFinite(value)) {
    throw new TypeError(`${name} must be a finite number`);
  }
  return value;
}

export function isValidTile(tileX, tileY, grid = COMMONS_WORLD) {
  return Number.isInteger(tileX)
    && Number.isInteger(tileY)
    && tileX >= 0
    && tileX < grid.columns
    && tileY >= 0
    && tileY < grid.rows;
}

export function assertValidTile(tileX, tileY, grid = COMMONS_WORLD) {
  if (!isValidTile(tileX, tileY, grid)) {
    throw new RangeError(`tile ${tileX},${tileY} is outside the Commons world`);
  }
  return { tile_x: tileX, tile_y: tileY };
}

export function projectGround(u, v, h = 0, grid = COMMONS_WORLD) {
  finite(u, 'u');
  finite(v, 'v');
  finite(h, 'h');
  return {
    x: grid.originX + (u - v) * (grid.tileWidth / 2),
    y: grid.originY + (u + v) * (grid.tileHeight / 2) - h,
  };
}

export function unprojectGround(pixelX, pixelY, h = 0, grid = COMMONS_WORLD) {
  finite(pixelX, 'pixelX');
  finite(pixelY, 'pixelY');
  finite(h, 'h');
  const u = (pixelX - grid.originX) / (grid.tileWidth / 2);
  const v = (pixelY + h - grid.originY) / (grid.tileHeight / 2);
  return {
    u: (u + v) / 2,
    v: (v - u) / 2,
  };
}

export function tileToGround(tileX, tileY, grid = COMMONS_WORLD) {
  assertValidTile(tileX, tileY, grid);
  return { u: tileX, v: tileY };
}

export function groundToTile(u, v, grid = COMMONS_WORLD) {
  finite(u, 'u');
  finite(v, 'v');
  const tileX = Math.round(u);
  const tileY = Math.round(v);
  if (Math.abs(u - tileX) > 0.5 || Math.abs(v - tileY) > 0.5) return null;
  return isValidTile(tileX, tileY, grid) ? { tile_x: tileX, tile_y: tileY } : null;
}

export function directionForDelta(deltaU, deltaV) {
  const key = `${deltaU},${deltaV}`;
  return COMMONS_DIRECTION_BY_DELTA[key] || null;
}

export function depthForGround(u, v, depthOffset = 0, grid = COMMONS_WORLD) {
  finite(u, 'u');
  finite(v, 'v');
  finite(depthOffset, 'depthOffset');
  return (u + v) * (grid.tileHeight / 2) + depthOffset;
}

export function getBackingStoreSize(displayWidth, displayHeight, devicePixelRatio = 1, maxDpr = 2) {
  finite(displayWidth, 'displayWidth');
  finite(displayHeight, 'displayHeight');
  finite(devicePixelRatio, 'devicePixelRatio');
  finite(maxDpr, 'maxDpr');
  if (displayWidth <= 0 || displayHeight <= 0 || maxDpr <= 0) {
    throw new RangeError('display dimensions and maxDpr must be positive');
  }
  const dpr = Math.min(Math.max(devicePixelRatio, 1), maxDpr);
  return {
    width: Math.max(1, Math.round(displayWidth * dpr)),
    height: Math.max(1, Math.round(displayHeight * dpr)),
    dpr,
  };
}

export function nonNegativeModulo(value, divisor) {
  finite(value, 'value');
  finite(divisor, 'divisor');
  if (divisor <= 0) throw new RangeError('divisor must be positive');
  return ((value % divisor) + divisor) % divisor;
}
