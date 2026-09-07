import { describe, expect, it } from 'vitest';
import { easternWallTimeToUTC, formatTournamentDateTime, utcToEasternWallTime } from './timezone.js';

describe('easternWallTimeToUTC', () => {
  it('converts an EDT (summer) wall-clock time to UTC', () => {
    expect(easternWallTimeToUTC('2026-08-15T18:00')).toBe('2026-08-15T22:00:00.000Z');
  });

  it('converts an EST (winter) wall-clock time to UTC', () => {
    expect(easternWallTimeToUTC('2026-01-15T18:00')).toBe('2026-01-15T23:00:00.000Z');
  });

  it('handles the spring-forward DST transition day', () => {
    // Clocks spring forward on 2026-03-08; 2:30 AM doesn't exist that day,
    // but an afternoon time should still resolve using the post-transition
    // (EDT) offset.
    expect(easternWallTimeToUTC('2026-03-08T14:30')).toBe('2026-03-08T18:30:00.000Z');
  });

  it('returns null for an empty value', () => {
    expect(easternWallTimeToUTC('')).toBeNull();
  });
});

describe('utcToEasternWallTime', () => {
  it('round-trips a UTC timestamp back to the same wall-clock string', () => {
    const utc = easternWallTimeToUTC('2026-08-15T18:00');
    expect(utcToEasternWallTime(utc)).toBe('2026-08-15T18:00');
  });

  it('round-trips across the winter offset too', () => {
    const utc = easternWallTimeToUTC('2026-01-15T18:00');
    expect(utcToEasternWallTime(utc)).toBe('2026-01-15T18:00');
  });

  it('returns an empty string for a falsy value', () => {
    expect(utcToEasternWallTime(null)).toBe('');
  });
});

describe('formatTournamentDateTime', () => {
  it('renders a friendly date/time without ever labeling the timezone', () => {
    const formatted = formatTournamentDateTime('2026-08-15T22:00:00.000Z');
    expect(formatted).toBe('Aug 15, 2026, 6:00 PM');
    expect(formatted).not.toMatch(/EST|EDT|GMT|UTC/);
  });
});
