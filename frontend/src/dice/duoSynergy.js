const NEUTRAL_MARGIN = 0.05;

export function isOnExpected(synergy) {
  return Math.abs(synergy.wins_above_expected) < NEUTRAL_MARGIN;
}

export function synergyDescription(synergy, { short = false } = {}) {
  if (isOnExpected(synergy)) return 'Right on expected';
  const difference = synergy.wins_above_expected;
  const amount = Math.abs(difference).toFixed(1);
  const direction = difference < 0 ? 'under' : 'over';
  if (short) return `${amount} ${direction}`;
  return `${amount} ${amount === '1.0' ? 'win' : 'wins'} ${direction} expected`;
}
