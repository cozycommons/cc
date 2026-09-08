export const COMMONS_GRID = Object.freeze({
  columns: 16,
  rows: 16,
  width: 512,
  height: 512,
  tileWidth: 32,
  tileHeight: 20,
  originX: 256,
  originY: 180,
});

export const COMMONS_FOOTPRINTS = Object.freeze({
  'orange-sofa': Object.freeze({ cells: [[-1, 0], [0, 0], [1, 0]] }),
  'green-loveseat': Object.freeze({ cells: [[0, 0], [1, 0]] }),
  'red-armchair': Object.freeze({ cells: [[0, 0]] }),
  'dining-table': Object.freeze({ cells: [[-1, 0], [0, 0], [1, 0]] }),
  'dining-chair': Object.freeze({ cells: [[0, 0]] }),
  'record-console': Object.freeze({ cells: [[-1, 0], [0, 0], [1, 0]] }),
  'coffee-table': Object.freeze({ cells: [[-1, 0], [0, 0]] }),
  'area-rug': Object.freeze({
    cells: [[-1, -1], [0, -1], [1, -1], [-1, 0], [0, 0], [1, 0]],
    blocks_movement: false,
  }),
  'floor-lamp': Object.freeze({ cells: [[0, 0]] }),
  topiary: Object.freeze({ cells: [[0, 0]] }),
  palm: Object.freeze({ cells: [[0, 0]] }),
  'bar-stool': Object.freeze({ cells: [[0, 0]] }),
});

function finiteNumber(value, fallback = 0) {
  return Number.isFinite(Number(value)) ? Number(value) : fallback;
}

export function clampTile(value, maximum) {
  return Math.min(maximum - 1, Math.max(0, Math.round(finiteNumber(value))));
}

export function normalizeTile(tileX, tileY) {
  return {
    tile_x: clampTile(tileX, COMMONS_GRID.columns),
    tile_y: clampTile(tileY, COMMONS_GRID.rows),
  };
}

export function tileKey(tileX, tileY) {
  const tile = normalizeTile(tileX, tileY);
  return `${tile.tile_x}:${tile.tile_y}`;
}

export function tileDistance(first, second) {
  const a = normalizeTile(first?.tile_x, first?.tile_y);
  const b = normalizeTile(second?.tile_x, second?.tile_y);
  return Math.abs(a.tile_x - b.tile_x) + Math.abs(a.tile_y - b.tile_y);
}

export function tileToPixel(tileX, tileY, grid = COMMONS_GRID) {
  const tile = normalizeTile(tileX, tileY);
  return {
    x: grid.originX + (tile.tile_x - tile.tile_y) * (grid.tileWidth / 2),
    y: grid.originY + (tile.tile_x + tile.tile_y) * (grid.tileHeight / 2),
  };
}

export function pixelToTile(pixelX, pixelY, grid = COMMONS_GRID) {
  const u = (finiteNumber(pixelX) - grid.originX) / (grid.tileWidth / 2);
  const v = (finiteNumber(pixelY) - grid.originY) / (grid.tileHeight / 2);
  return normalizeTile((u + v) / 2, (v - u) / 2);
}

export function normalizedToTile(x, y, grid = COMMONS_GRID) {
  return pixelToTile(
    finiteNumber(x, 0.5) * grid.width,
    finiteNumber(y, 0.5) * grid.height,
    grid,
  );
}

export function tileToNormalized(tileX, tileY, grid = COMMONS_GRID) {
  const pixel = tileToPixel(tileX, tileY, grid);
  return { x: pixel.x / grid.width, y: pixel.y / grid.height };
}

export function isWalkableTile(tileX, tileY, grid = COMMONS_GRID) {
  return Number.isInteger(tileX)
    && Number.isInteger(tileY)
    && tileX >= 0
    && tileX < grid.columns
    && tileY >= 0
    && tileY < grid.rows;
}

function stateEntityTile(entity) {
  if (Number.isInteger(entity?.tile_x) && Number.isInteger(entity?.tile_y)) {
    return normalizeTile(entity.tile_x, entity.tile_y);
  }
  return normalizedToTile(entity?.x, entity?.y);
}

export function getEntityFootprint(entity) {
  const cells = entity?.footprint?.cells || COMMONS_FOOTPRINTS[entity?.asset]?.cells || [[0, 0]];
  return {
    cells: cells.filter((cell) => Array.isArray(cell) && cell.length === 2),
    blocks_movement: entity?.footprint?.blocks_movement
      ?? COMMONS_FOOTPRINTS[entity?.asset]?.blocks_movement
      ?? true,
  };
}

function occupiedCells(entity, tile) {
  return getEntityFootprint(entity).cells.map(([offsetX, offsetY]) => ({
    tile_x: tile.tile_x + offsetX,
    tile_y: tile.tile_y + offsetY,
  }));
}

function cellsOverlap(first, second) {
  const secondKeys = new Set(second.map((cell) => tileKey(cell.tile_x, cell.tile_y)));
  return first.some((cell) => secondKeys.has(tileKey(cell.tile_x, cell.tile_y)));
}

export function isTileAvailable(state, tile, { entityType, entityId } = {}) {
  if (!isWalkableTile(tile?.tile_x, tile?.tile_y)) return false;
  const movingEntity = entityType === 'object'
    ? state?.objects?.[entityId]
    : state?.actors?.[entityId];
  const candidateCells = occupiedCells(movingEntity || {}, tile);
  if (candidateCells.some((cell) => !isWalkableTile(cell.tile_x, cell.tile_y))) return false;
  const candidateKeys = candidateCells.map((cell) => tileKey(cell.tile_x, cell.tile_y));
  const blocked = new Set(
    (state?.grid?.blocked || [])
      .filter((entry) => Array.isArray(entry) && entry.length === 2)
      .map(([x, y]) => tileKey(x, y)),
  );
  if (candidateKeys.some((key) => blocked.has(key))) return false;

  const objects = Object.values(state?.objects || {});
  if (objects.some((entity) => {
    if ((entityType === 'object' && entity.id === entityId) || !getEntityFootprint(entity).blocks_movement) return false;
    return cellsOverlap(candidateCells, occupiedCells(entity, stateEntityTile(entity)));
  })) {
    return false;
  }
  const actors = Object.values(state?.actors || {});
  return !actors.some((entity) => {
    if (entityType === 'actor' && entity.id === entityId) return false;
    return cellsOverlap(candidateCells, occupiedCells(entity, stateEntityTile(entity)));
  });
}

export function findTilePath(state, startTile, targetTile, options = {}) {
  const start = normalizeTile(startTile?.tile_x, startTile?.tile_y);
  const target = normalizeTile(targetTile?.tile_x, targetTile?.tile_y);
  if (tileKey(start.tile_x, start.tile_y) === tileKey(target.tile_x, target.tile_y)) return [];
  if (!isTileAvailable(state, target, options)) return [];

  const previous = new Map([[tileKey(start.tile_x, start.tile_y), null]]);
  const queue = [start];
  const directions = [
    { tile_x: 1, tile_y: 0 },
    { tile_x: -1, tile_y: 0 },
    { tile_x: 0, tile_y: 1 },
    { tile_x: 0, tile_y: -1 },
  ];

  while (queue.length) {
    const current = queue.shift();
    for (const direction of directions) {
      const next = {
        tile_x: current.tile_x + direction.tile_x,
        tile_y: current.tile_y + direction.tile_y,
      };
      const key = tileKey(next.tile_x, next.tile_y);
      if (!isWalkableTile(next.tile_x, next.tile_y) || previous.has(key)) continue;
      if (!isTileAvailable(state, next, options)) continue;
      previous.set(key, { tile: next, from: current });
      if (key === tileKey(target.tile_x, target.tile_y)) {
        const path = [];
        let cursor = key;
        while (cursor) {
          const step = previous.get(cursor);
          if (!step) break;
          path.unshift(step.tile);
          cursor = tileKey(step.from.tile_x, step.from.tile_y);
        }
        return path;
      }
      queue.push(next);
    }
  }
  return [];
}
