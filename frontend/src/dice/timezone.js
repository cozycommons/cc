// Dice assumes every tournament time is US Eastern (America/New_York) —
// the group's home timezone — and never surfaces the zone in the UI. All
// conversion between that "assumed" wall-clock time and the UTC timestamps
// the backend stores happens here.
const DICE_TIMEZONE = 'America/New_York';

// Offset (in minutes) of `date` (a UTC instant) as observed in `timeZone`,
// e.g. -240 for EDT. Used to round-trip a wall-clock time through DST
// without a timezone library: format the instant in the target zone, then
// see how far that reads from the same instant read as UTC.
function timeZoneOffsetMinutes(date, timeZone) {
  const dtf = new Intl.DateTimeFormat('en-US', {
    timeZone,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  });
  const parts = dtf.formatToParts(date).reduce((acc, p) => {
    acc[p.type] = p.value;
    return acc;
  }, {});
  const asUTC = Date.UTC(parts.year, parts.month - 1, parts.day, parts.hour, parts.minute, parts.second);
  return (asUTC - date.getTime()) / 60000;
}

// Converts a `<input type="datetime-local">` value ("2026-08-15T18:00"),
// interpreted as Dice's assumed timezone, into a UTC ISO string.
export function easternWallTimeToUTC(localDateTimeString) {
  if (!localDateTimeString) return null;
  const [datePart, timePart] = localDateTimeString.split('T');
  const [year, month, day] = datePart.split('-').map(Number);
  const [hour, minute] = (timePart || '00:00').split(':').map(Number);
  const wallClockAsUTC = Date.UTC(year, month - 1, day, hour, minute);

  // Two passes resolve the DST edge case where the offset itself changes
  // between the first guess and the corrected instant.
  let instant = wallClockAsUTC;
  for (let i = 0; i < 2; i += 1) {
    const offset = timeZoneOffsetMinutes(new Date(instant), DICE_TIMEZONE);
    instant = wallClockAsUTC - offset * 60000;
  }
  return new Date(instant).toISOString();
}

// Converts a stored UTC ISO timestamp into the value a
// `<input type="datetime-local">` expects, expressed in Dice's assumed
// timezone.
export function utcToEasternWallTime(isoString) {
  if (!isoString) return '';
  const dtf = new Intl.DateTimeFormat('en-US', {
    timeZone: DICE_TIMEZONE,
    hourCycle: 'h23',
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  });
  const parts = dtf.formatToParts(new Date(isoString)).reduce((acc, p) => {
    acc[p.type] = p.value;
    return acc;
  }, {});
  return `${parts.year}-${parts.month}-${parts.day}T${parts.hour}:${parts.minute}`;
}

// Renders a stored UTC ISO timestamp for display, e.g. "Aug 15, 2026, 6:00 PM".
// Deliberately doesn't append a timezone label — Dice's timezone is assumed.
export function formatTournamentDateTime(isoString) {
  return new Date(isoString).toLocaleString('en-US', {
    timeZone: DICE_TIMEZONE,
    month: 'short',
    day: 'numeric',
    year: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}
