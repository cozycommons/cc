export function synergyDescription(synergy) {
  const difference = synergy.wins_above_expected;
  return `${Math.abs(difference).toFixed(1)} wins ${difference < 0 ? 'under' : 'over'} expected`;
}
