const finite = value => Number.isFinite(value);
const pair = value => Array.isArray(value) && value.length === 2 && value.every(finite);

// Cumulative score paths for one matchup (days are in date order). `actual` runs through
// the last observed day; `projected` starts at that day's expected finish and adds each
// later day's expectation, ending on the published projected totals.
export function scorePath(matchup) {
  const days = matchup.days || [];
  // Live days count points so far (a side with none yet counts zero); pre-tip live days are projections.
  const live = day => day.state === 'live' && Array.isArray(day.actual) && day.actual.some(finite);
  const isFuture = day => day.state === 'projected' || (day.state === 'live' && !live(day));
  const rows = days.map(day => ({ date: day.date, state: day.state, actual: null, projected: null }));
  const firstFuture = days.findIndex(isFuture);
  const start = firstFuture === -1 ? days.length : firstFuture;
  const sums = [0, 0];
  for (let i = 0; i < start; i++) {
    const actual = live(days[i]) ? days[i].actual.map(value => value ?? 0) : days[i].actual;
    if (!pair(actual)) break; // never treat a missing actual as zero
    actual.forEach((value, side) => { sums[side] += value; });
    rows[i].actual = [...sums];
  }
  if (!pair(matchup.projected_totals)) return rows;
  const add = (total, day) => total.map((value, side) => value + (day.expected?.[side] ?? 0));
  const rest = days.slice(start).reduce(add, [0, 0]);
  let running = matchup.projected_totals.map((value, side) => value - rest[side]);
  if (start > 0) rows[start - 1].projected = running;
  for (let i = start; i < days.length; i++) {
    running = add(running, days[i]);
    rows[i].projected = running;
  }
  return rows;
}

export function favorite(matchup) {
  if (!finite(matchup.chance) || matchup.chance === 50) return null;
  return matchup.chance > 50 ? 0 : 1;
}

// Closest races first; unavailable matchups last.
export function orderMatchups(matchups = []) {
  return [...matchups].sort((a, b) => (a.unavailable ? 1 : 0) - (b.unavailable ? 1 : 0)
    || Math.abs((a.chance ?? 50) - 50) - Math.abs((b.chance ?? 50) - 50));
}
