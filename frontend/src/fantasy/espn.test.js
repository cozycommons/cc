import { expect, it } from 'vitest';
import { playerProfile } from './espn.js';
it('encodes player IDs into a public HTTPS path without league configuration', () => {
  expect(playerProfile(123)).toBe('https://www.espn.com/nba/player/_/id/123');
  expect(playerProfile('1/?leagueId=secret')).toBe('https://www.espn.com/nba/player/_/id/1%2F%3FleagueId%3Dsecret');
});
