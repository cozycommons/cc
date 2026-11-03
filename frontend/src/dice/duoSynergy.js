// Rates round half up to whole percents, matching the backend. A pair is
// neutral when its together and expected rates display the same.
export function wholePercent(rate) {
  return Math.floor(rate * 100 + 0.5);
}

export function synergyRates(synergy) {
  return {
    together: wholePercent(synergy.wins / synergy.games),
    expected: wholePercent(synergy.expected_wins / synergy.games),
  };
}

export function synergyGap(synergy) {
  const { together, expected } = synergyRates(synergy);
  return together - expected;
}

export function isOnExpected(synergy) {
  return synergyGap(synergy) === 0;
}

export function synergyTitle(synergy) {
  const gap = synergyGap(synergy);
  if (gap === 0) return 'Right on expected';
  return gap > 0 ? 'Better together' : 'Better apart';
}

export function synergyDescription(synergy) {
  const { together, expected } = synergyRates(synergy);
  return `${together}% wins, ${expected}% expected`;
}
