export function rankLeaderboard(entries, valueKey, { provisionalKey } = {}) {
  let previousValue;
  let previousRank = 0;

  const ranked = (entries || []).map((entry, index) => {
    if (provisionalKey && entry[provisionalKey]) return { ...entry, rank: null };

    const value = entry[valueKey];
    const rank = index > 0 && value === previousValue ? previousRank : index + 1;
    previousValue = value;
    previousRank = rank;
    return { ...entry, rank };
  });
  const rankCounts = ranked.reduce((counts, entry) => {
    if (entry.rank !== null) counts.set(entry.rank, (counts.get(entry.rank) || 0) + 1);
    return counts;
  }, new Map());
  return ranked.map((entry) => ({ ...entry, tied: entry.rank !== null && rankCounts.get(entry.rank) > 1 }));
}

export function leaderboardPreview(entries, currentUserId, limit = 3) {
  const leaders = (entries || []).slice(0, limit);
  const current = currentUserId
    ? (entries || []).find((entry) => entry.user_id === currentUserId)
    : null;

  return {
    leaders,
    current: current && !leaders.some((entry) => entry.user_id === current.user_id) ? current : null,
  };
}
