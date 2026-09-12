import {
  directionForDelta,
  isValidTile,
  nonNegativeModulo,
  tileToGround,
} from '../world/geometry.js';

const KINDS = new Set(['hold', 'walk']);
const MAX_DURATION_MS = 24 * 60 * 60 * 1000;
const MAX_WALK_MS = 20 * 1000;

function fail(message) {
  return { valid: false, error: message };
}

function tileFromArray(value) {
  if (!Array.isArray(value) || value.length !== 2) return null;
  const [u, v] = value;
  return Number.isInteger(u) && Number.isInteger(v) && isValidTile(u, v)
    ? { tile_x: u, tile_y: v }
    : null;
}

function sameTile(first, second) {
  return first?.tile_x === second?.tile_x && first?.tile_y === second?.tile_y;
}

function segmentDuration(segment) {
  if (segment.kind === 'hold') return segment.duration_ms;
  return segment.edge_durations_ms.reduce((total, duration) => total + duration, 0);
}

function validateSegment(segment, previousTile) {
  if (!segment || !KINDS.has(segment.kind)) return fail('unknown segment kind');
  if (segment.kind === 'hold') {
    const tile = tileFromArray(segment.tile);
    if (!tile || !Number.isInteger(segment.duration_ms) || segment.duration_ms <= 0 || segment.duration_ms > MAX_DURATION_MS) {
      return fail('invalid hold segment');
    }
    if (typeof segment.facing !== 'string' || !segment.facing) return fail('hold facing is required');
    if (previousTile && !sameTile(previousTile, tile)) return fail('hold is disconnected from the previous segment');
    return { valid: true, endTile: tile, duration: segment.duration_ms };
  }

  if (!Array.isArray(segment.waypoints) || segment.waypoints.length < 2) return fail('walk needs two or more waypoints');
  if (!Array.isArray(segment.edge_durations_ms) || segment.edge_durations_ms.length !== segment.waypoints.length - 1) {
    return fail('walk durations must match its edges');
  }
  const waypoints = segment.waypoints.map(tileFromArray);
  if (waypoints.some((tile) => !tile)) return fail('walk contains an invalid waypoint');
  if (previousTile && !sameTile(previousTile, waypoints[0])) return fail('walk is disconnected from the previous segment');
  const directions = [];
  for (let index = 0; index < waypoints.length - 1; index += 1) {
    const deltaU = waypoints[index + 1].tile_x - waypoints[index].tile_x;
    const deltaV = waypoints[index + 1].tile_y - waypoints[index].tile_y;
    const direction = directionForDelta(deltaU, deltaV);
    const duration = segment.edge_durations_ms[index];
    if (!direction || !Number.isInteger(duration) || duration <= 0 || duration > MAX_DURATION_MS) {
      return fail('walk contains an invalid edge');
    }
    directions.push(direction);
  }
  const duration = segment.edge_durations_ms.reduce((total, edge) => total + edge, 0);
  if (duration <= 0 || duration > MAX_DURATION_MS) return fail('walk duration is invalid');
  return { valid: true, endTile: waypoints.at(-1), duration, waypoints, directions };
}

export function validateAmbientProgram(program, actorIds = []) {
  if (!program || program.enabled !== true) {
    if (program && program.enabled === false && Number.isInteger(program.revision) && typeof program.reason === 'string') {
      return { valid: true, disabled: true };
    }
    return fail('ambient program must be enabled or explicitly disabled');
  }
  if (!Number.isInteger(program.revision) || program.revision < 0) return fail('invalid ambient revision');
  if (!Number.isFinite(program.epoch_ms) || !Number.isInteger(program.cycle_ms) || program.cycle_ms <= 0) {
    return fail('invalid ambient clock');
  }
  if (!Number.isInteger(program.seed) || !program.actors || typeof program.actors !== 'object') return fail('invalid ambient metadata');
  const expectedActors = new Set(actorIds);
  const tracks = Object.entries(program.actors);
  if (tracks.some(([id]) => expectedActors.size > 0 && !expectedActors.has(id))) return fail('ambient track has an unknown actor');
  if (expectedActors.size > 0 && [...expectedActors].some((id) => !Object.hasOwn(program.actors, id))) return fail('ambient track is missing an actor');

  const walkEvents = [];
  for (const [, segments] of tracks) {
    if (!Array.isArray(segments) || segments.length === 0) return fail('actor needs a non-empty ambient track');
    let elapsed = 0;
    let previousTile = null;
    let walkingDuration = 0;
    for (const segment of segments) {
      const result = validateSegment(segment, previousTile);
      if (!result.valid) return result;
      elapsed += result.duration;
      previousTile = result.endTile;
      if (segment.kind === 'walk') {
        walkingDuration += result.duration;
        walkEvents.push([elapsed - result.duration, 1]);
        walkEvents.push([elapsed, -1]);
      }
    }
    if (elapsed !== program.cycle_ms) return fail('actor track does not fill the cycle');
    if (walkingDuration > MAX_WALK_MS) return fail('actor walks for too much of the cycle');
    const first = tileFromArray(segments[0].kind === 'hold' ? segments[0].tile : segments[0].waypoints[0]);
    if (!sameTile(first, previousTile)) return fail('ambient cycle wraps discontinuously');
  }
  walkEvents.sort(([timeA, deltaA], [timeB, deltaB]) => timeA - timeB || deltaA - deltaB);
  let activeWalkers = 0;
  let maximumWalkers = 0;
  for (const [, delta] of walkEvents) {
    activeWalkers += delta;
    maximumWalkers = Math.max(maximumWalkers, activeWalkers);
  }
  if (maximumWalkers > Number(program.max_walkers || 1)) return fail('ambient walk count exceeds program limit');
  return { valid: true, disabled: false };
}

function disabledPose(home) {
  const tile = tileFromArray([home?.tile_x, home?.tile_y]) || { tile_x: 0, tile_y: 0 };
  return {
    mode: 'home',
    tile_x: tile.tile_x,
    tile_y: tile.tile_y,
    u: tile.tile_x,
    v: tile.tile_y,
    facing: home?.facing || 'front',
    segmentIndex: -1,
    progress: 0,
  };
}

export function evaluateAmbientPose(program, actorId, timeMs, home) {
  if (!program || program.enabled !== true) return disabledPose(home);
  const track = program.actors?.[actorId];
  if (!Array.isArray(track) || !Number.isFinite(timeMs)) return disabledPose(home);
  let remaining = nonNegativeModulo(timeMs - program.epoch_ms, program.cycle_ms);
  for (let segmentIndex = 0; segmentIndex < track.length; segmentIndex += 1) {
    const segment = track[segmentIndex];
    const duration = segmentDuration(segment);
    if (remaining < duration || segmentIndex === track.length - 1) {
      if (segment.kind === 'hold') {
        const tile = tileFromArray(segment.tile);
        return {
          mode: 'hold',
          tile_x: tile.tile_x,
          tile_y: tile.tile_y,
          u: tile.tile_x,
          v: tile.tile_y,
          facing: segment.facing,
          segmentIndex,
          progress: duration ? remaining / duration : 0,
        };
      }
      let edgeElapsed = remaining;
      for (let edgeIndex = 0; edgeIndex < segment.edge_durations_ms.length; edgeIndex += 1) {
        const edgeDuration = segment.edge_durations_ms[edgeIndex];
        if (edgeElapsed < edgeDuration || edgeIndex === segment.edge_durations_ms.length - 1) {
          const start = tileFromArray(segment.waypoints[edgeIndex]);
          const end = tileFromArray(segment.waypoints[edgeIndex + 1]);
          const progress = edgeDuration ? Math.min(1, edgeElapsed / edgeDuration) : 1;
          return {
            mode: 'walk',
            tile_x: end.tile_x,
            tile_y: end.tile_y,
            u: start.tile_x + (end.tile_x - start.tile_x) * progress,
            v: start.tile_y + (end.tile_y - start.tile_y) * progress,
            facing: directionForDelta(end.tile_x - start.tile_x, end.tile_y - start.tile_y),
            segmentIndex,
            edgeIndex,
            progress,
          };
        }
        edgeElapsed -= edgeDuration;
      }
    }
    remaining -= duration;
  }
  return disabledPose(home);
}

export function settleAmbientPose(program, actorId, timeMs, home) {
  const pose = evaluateAmbientPose(program, actorId, timeMs, home);
  if (pose.mode !== 'walk') return pose;
  const segment = program?.actors?.[actorId]?.[pose.segmentIndex];
  const endpoint = tileFromArray(segment?.waypoints?.[pose.edgeIndex + 1]);
  if (!endpoint) return pose;
  return {
    ...pose,
    mode: 'hold',
    tile_x: endpoint.tile_x,
    tile_y: endpoint.tile_y,
    u: endpoint.tile_x,
    v: endpoint.tile_y,
    progress: 1,
  };
}

export function poseGroundPoint(pose) {
  if (!Number.isFinite(pose?.u) || !Number.isFinite(pose?.v)) {
    return tileToGround(pose.tile_x, pose.tile_y);
  }
  return { u: pose.u, v: pose.v };
}
