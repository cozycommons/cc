import contract from '../../../../shared/commons/scene-contract-v1.json';
import { validateAmbientProgram } from '../ambient/timeline.js';

export const COMMONS_SCENE_CONTRACT = Object.freeze(contract);

function invalid(error) {
  return { valid: false, error };
}

function isTile(value, maximum) {
  return Number.isInteger(value) && value >= 0 && value < maximum;
}

function validateEntities(entities, world, allowedAssets) {
  if (!entities || typeof entities !== 'object' || Array.isArray(entities)) return false;
  return Object.values(entities).every((entity) => {
    if (!entity || typeof entity !== 'object' || !allowedAssets.has(entity.asset)) return false;
    if (Number.isInteger(entity.tile_x) || Number.isInteger(entity.tile_y)) {
      return isTile(entity.tile_x, world.columns) && isTile(entity.tile_y, world.rows);
    }
    return Number.isFinite(entity.x) && Number.isFinite(entity.y);
  });
}

export function validateSceneSnapshot(snapshot) {
  if (!snapshot || typeof snapshot !== 'object') return invalid('scene snapshot is not an object');
  if (typeof snapshot.id !== 'string' || !Number.isInteger(snapshot.layout_version) || !Number.isInteger(snapshot.version)) {
    return invalid('scene snapshot metadata is invalid');
  }
  if (!Number.isFinite(Number(snapshot.server_time_ms))) return invalid('scene server time is missing');
  const state = snapshot.state;
  if (!state || typeof state !== 'object' || Array.isArray(state)) return invalid('scene state is missing');
  const world = COMMONS_SCENE_CONTRACT.world;
  const allowedAssets = new Set(COMMONS_SCENE_CONTRACT.allowed_assets);
  if (!validateEntities(state.objects, world, allowedAssets) || !validateEntities(state.actors, world, allowedAssets)) {
    return invalid('scene entity catalog or coordinates are invalid');
  }

  const schemaVersion = Number(state.schema_version || 0);
  const isLegacy = schemaVersion < COMMONS_SCENE_CONTRACT.max_schema_version || !state.catalog_version;
  if (isLegacy) return { valid: true, legacy: true };
  if (state.catalog_version !== COMMONS_SCENE_CONTRACT.catalog_version) return invalid('scene catalog is unsupported');
  const actorIds = Object.keys(state.actors);
  const ambient = validateAmbientProgram(state.ambient, actorIds);
  if (!ambient.valid) return invalid(`ambient program is invalid: ${ambient.error}`);
  return { valid: true, legacy: false };
}
