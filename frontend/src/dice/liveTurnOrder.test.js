import { describe, expect, it } from 'vitest';
import { deriveLiveTurn } from './liveTurnOrder.js';

const observation = (id, sequence, thrower, team, extra = {}) => ({
  id,
  sequence,
  kind: 'observation',
  thrower_id: thrower,
  throwing_team_id: team,
  ...extra,
});

const game = (events = []) => ({
  team_order: ['blue', 'clay'],
  teams: { blue: ['alice', 'bea'], clay: ['cam', 'dev'] },
  events,
});

describe('deriveLiveTurn', () => {
  it('starts with the saved first player', () => {
    expect(deriveLiveTurn(game()).nextThrowerId).toBe('alice');
  });

  it('keeps a team for two throws, then switches teams', () => {
    const afterAlice = deriveLiveTurn(game([
      observation('a1', 1, 'alice', 'blue'),
    ]));
    expect(afterAlice.nextThrowerId).toBe('bea');
    expect(afterAlice.throwOrder).toEqual(['bea', 'alice', 'cam', 'dev']);
    const afterBlue = deriveLiveTurn(game([
      observation('a1', 1, 'alice', 'blue'),
      observation('b1', 2, 'bea', 'blue'),
    ]));
    expect(afterBlue.nextThrowerId).toBe('cam');
    expect(afterBlue.throwOrder).toEqual(['cam', 'dev', 'alice', 'bea']);
  });

  it('makes a confirmed out-of-order first throw sticky without saved lineup state', () => {
    const events = [
      observation('b1', 1, 'bea', 'blue'),
      observation('a1', 2, 'alice', 'blue'),
      observation('c1', 3, 'cam', 'clay'),
      observation('d1', 4, 'dev', 'clay'),
    ];
    const turn = deriveLiveTurn(game(events));
    expect(turn.nextThrowerId).toBe('bea');
    expect(turn.throwOrder).toEqual(['bea', 'alice', 'cam', 'dev']);
  });

  it('uses the last teammate for loose ABA history', () => {
    const events = [
      observation('a1', 1, 'alice', 'blue'),
      observation('b1', 2, 'bea', 'blue'),
      observation('a2', 3, 'alice', 'blue'),
      observation('c1', 4, 'cam', 'clay'),
      observation('d1', 5, 'dev', 'clay'),
    ];
    expect(deriveLiveTurn(game(events)).nextThrowerId).toBe('bea');
  });

  it('ignores removed, retossed, and superseded observations', () => {
    const removed = [
      observation('a1', 1, 'alice', 'blue'),
      { id: 'undo', sequence: 2, kind: 'correction', target_event_id: 'a1' },
    ];
    expect(deriveLiveTurn(game(removed)).nextThrowerId).toBe('alice');

    const retossed = [
      observation('a1', 1, 'alice', 'blue'),
      { id: 'retoss', sequence: 2, kind: 'retoss_decision', target_event_id: 'a1' },
    ];
    expect(deriveLiveTurn(game(retossed)).nextThrowerId).toBe('alice');

    const corrected = [
      observation('a1', 1, 'alice', 'blue'),
      { id: 'fix', sequence: 2, kind: 'correction', target_event_id: 'a1' },
      observation('replacement', 3, 'bea', 'blue', { replacement_for: 'a1' }),
    ];
    expect(deriveLiveTurn(game(corrected)).nextThrowerId).toBe('alice');
  });
});
