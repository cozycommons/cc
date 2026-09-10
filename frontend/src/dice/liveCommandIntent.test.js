import { describe, expect, it } from 'vitest';
import {
  clearLiveCanonicalVersion,
  clearLiveCommandIntent,
  readLiveCanonicalVersion,
  readLiveCommandIntent,
  writeLiveCanonicalVersion,
  writeLiveCommandIntent,
} from './liveCommandIntent.js';

const command = {
  client_command_id: 'command-1',
  expected_version: 7,
  match_elapsed_ms: 0,
  kind: 'record_throw',
  thrower_id: 'alice',
  outcome: 'point',
};

describe('live command intent storage', () => {
  it('round-trips the exact command within one user and game scope', () => {
    const storage = window.localStorage;
    storage.clear();
    expect(writeLiveCommandIntent(storage, 'user-1', 'match-1', { state: 'pending', command })).toBe(true);
    expect(readLiveCommandIntent(storage, 'user-1', 'match-1')).toEqual({ version: 1, state: 'pending', command });
    expect(readLiveCommandIntent(storage, 'user-2', 'match-1')).toBeNull();
    expect(readLiveCommandIntent(storage, 'user-1', 'match-2')).toBeNull();
  });

  it('removes invalid or acknowledged records', () => {
    const storage = window.localStorage;
    storage.clear();
    storage.setItem('dice.live-command.v1:user-1:match-1', '{"version":1,"state":"pending","command":{}}');
    expect(readLiveCommandIntent(storage, 'user-1', 'match-1')).toBeNull();
    expect(storage.length).toBe(0);

    writeLiveCommandIntent(storage, 'user-1', 'match-1', { state: 'review', command });
    clearLiveCommandIntent(storage, 'user-1', 'match-1');
    expect(readLiveCommandIntent(storage, 'user-1', 'match-1')).toBeNull();
  });

  it('keeps newer canonical requirements when tabs finish out of order', () => {
    const storage = window.localStorage;
    storage.clear();
    writeLiveCanonicalVersion(storage, 'user-1', 'match-1', 9);
    writeLiveCanonicalVersion(storage, 'user-1', 'match-1', 8);
    expect(readLiveCanonicalVersion(storage, 'user-1', 'match-1')).toBe(9);
    clearLiveCanonicalVersion(storage, 'user-1', 'match-1', 8);
    expect(readLiveCanonicalVersion(storage, 'user-1', 'match-1')).toBe(9);
    clearLiveCanonicalVersion(storage, 'user-1', 'match-1', 9);
    expect(readLiveCanonicalVersion(storage, 'user-1', 'match-1')).toBe(0);
  });

  it('keeps scoring available when browser storage throws', () => {
    const storage = {
      getItem: () => { throw new Error('blocked'); },
      setItem: () => { throw new Error('blocked'); },
      removeItem: () => { throw new Error('blocked'); },
    };
    expect(readLiveCommandIntent(storage, 'user-1', 'match-1')).toBeNull();
    expect(writeLiveCommandIntent(storage, 'user-1', 'match-1', { state: 'pending', command })).toBe(false);
    expect(() => clearLiveCommandIntent(storage, 'user-1', 'match-1')).not.toThrow();
    expect(readLiveCanonicalVersion(storage, 'user-1', 'match-1')).toBe(0);
    expect(writeLiveCanonicalVersion(storage, 'user-1', 'match-1', 8)).toBe(false);
    expect(() => clearLiveCanonicalVersion(storage, 'user-1', 'match-1')).not.toThrow();
  });

});
