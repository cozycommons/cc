import { describe, expect, it } from 'vitest';
import { evaluateAmbientPose, poseGroundPoint, settleAmbientPose, validateAmbientProgram } from './timeline.js';

const program = {
  enabled: true,
  revision: 1,
  epoch_ms: 1_800_000_000_000,
  cycle_ms: 180000,
  seed: 42,
  max_walkers: 1,
  actors: {
    host: [
      { kind: 'hold', duration_ms: 176400, tile: [4, 4], facing: 'front_right' },
      { kind: 'walk', waypoints: [[4, 4], [5, 4], [6, 4]], edge_durations_ms: [900, 900] },
      { kind: 'walk', waypoints: [[6, 4], [5, 4], [4, 4]], edge_durations_ms: [900, 900] },
    ],
  },
};

describe('Commons ambient timeline', () => {
  it('validates a continuous track against the declared actor set', () => {
    expect(validateAmbientProgram(program, ['host'])).toEqual({ valid: true, disabled: false });
  });

  it('rejects a disconnected hold or a track with an incomplete cycle', () => {
    expect(validateAmbientProgram({
      ...program,
      actors: { host: [{ kind: 'hold', duration_ms: 180000, tile: [4, 4], facing: 'front_right' }, { kind: 'hold', duration_ms: 1, tile: [5, 4], facing: 'front_right' }] },
    }, ['host']).valid).toBe(false);
  });

  it('evaluates a fractional walk position and preserves the outgoing direction', () => {
    const pose = evaluateAmbientPose(program, 'host', program.epoch_ms + 177300);
    expect(pose.mode).toBe('walk');
    expect(pose.u).toBe(5);
    expect(pose.v).toBe(4);
    expect(pose.facing).toBe('front_right');
  });

  it('uses nonnegative cycle time before the epoch', () => {
    const pose = evaluateAmbientPose(program, 'host', program.epoch_ms - 900);
    expect(pose.mode).toBe('walk');
    expect(pose.u).toBeCloseTo(5);
    expect(pose.v).toBeCloseTo(4);
    expect(pose.facing).toBe('back_left');
  });

  it('returns a safe home pose for an explicitly disabled program', () => {
    expect(evaluateAmbientPose({ enabled: false, revision: 2, reason: 'invalidated' }, 'host', Date.now(), {
      tile_x: 7,
      tile_y: 8,
      facing: 'back_right',
    })).toMatchObject({ mode: 'home', tile_x: 7, tile_y: 8, facing: 'back_right' });
  });

  it('rejects a resident schedule that spends more than twenty seconds walking', () => {
    expect(validateAmbientProgram({
      ...program,
      cycle_ms: 260000,
      actors: {
        host: [
          { kind: 'hold', duration_ms: 200000, tile: [4, 4], facing: 'front_right' },
          { kind: 'walk', waypoints: [[4, 4], [5, 4]], edge_durations_ms: [21000] },
          { kind: 'walk', waypoints: [[5, 4], [4, 4]], edge_durations_ms: [21000] },
          { kind: 'hold', duration_ms: 18000, tile: [4, 4], facing: 'front_right' },
        ],
      },
    }, ['host']).valid).toBe(false);
  });

  it('keeps fractional ground coordinates when projecting a walk pose', () => {
    expect(poseGroundPoint({ tile_x: 5, tile_y: 4, u: 4.5, v: 4 })).toEqual({ u: 4.5, v: 4 });
  });

  it('settles an uncertain walk at the current edge endpoint', () => {
    expect(settleAmbientPose(program, 'host', program.epoch_ms + 176850)).toMatchObject({
      mode: 'hold',
      tile_x: 5,
      tile_y: 4,
      u: 5,
      v: 4,
      progress: 1,
    });
  });
});
