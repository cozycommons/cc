// Short reads of the snapshot. Everything here is derived from published numbers.
const r = value => Math.round(value);
const odds = value => (value > 99 ? '>99' : value < 1 ? '<1' : r(value));  // only used before a matchup is final
const isLeft = day => day.state === 'projected' || (day.state === 'live' && !(Array.isArray(day.actual) && day.actual.some(Number.isFinite)));
export const finished = matchup => (matchup.days || []).length > 0 && matchup.days.every(day => day.state === 'final');

// Games each side still has this week (projected days plus live days with no points yet).
export function gamesLeft(matchup) {
  return (matchup.days || []).filter(isLeft)
    .reduce((sum, day) => sum.map((value, side) => value + (Number.isFinite(day.games?.[side]) ? day.games[side] : 0)), [0, 0]);
}

// Who is favored, and the two facts behind it: the current lead and games left.
export function matchupRead(matchup) {
  const names = [matchup.home.name, matchup.away.name];
  if (finished(matchup)) {
    const [h, a] = matchup.scores.map(r);
    if (h === a) return { side: null, headline: `Tied ${h}–${a}`, facts: ['Final'] };
    const side = h > a ? 0 : 1;
    return { side, headline: `${names[side]} wins`, facts: ['Final', `${Math.max(h, a)}–${Math.min(h, a)}`] };
  }
  const side = matchup.chance >= 50 ? 0 : 1, other = 1 - side;
  const lead = r(matchup.scores[side] - matchup.scores[other]);
  const left = gamesLeft(matchup);
  const facts = [lead > 0 ? `Up ${lead}` : lead < 0 ? `Down ${-lead}` : 'Tied'];
  // The projected finish is the real reason for the odds, most of all when the favorite trails.
  const finish = r((matchup.projected_totals?.[side] ?? NaN) - (matchup.projected_totals?.[other] ?? NaN));
  if (Number.isFinite(finish)) facts.push(finish > 0 ? `Projected to win by ${finish}` : finish < 0 ? `Projected to lose by ${-finish}` : 'Projected even');
  if (!left[side] && !left[other]) facts.push('Last games in progress');
  else if (left[side] === left[other]) facts.push(`${left[side]} games left each`);
  else facts.push(`${left[side]} games left vs ${left[other]}`);
  return { side, headline: `${names[side]} ${odds(Math.max(matchup.chance, 100 - matchup.chance))}%`, facts };
}

// Players' actual vs expected points over finished days, per side (live games are partial).
export function playerSwings(matchup) {
  const totals = [new Map(), new Map()];
  for (const day of matchup.days || []) {
    if (!day.players || day.state !== 'final') continue;
    day.players.forEach((rows, side) => rows.forEach(player => {
      if (!Number.isFinite(player.points) || !Number.isFinite(player.expected)) return;
      const row = totals[side].get(player.id) || { id: player.id, name: player.name, actual: 0, expected: 0, games: 0 };
      row.actual += player.points; row.expected += player.expected; row.games += 1;
      if (player.acquired) row.acquired = player.acquired;  // latest tagged day wins; older untagged days don't erase it
      totals[side].set(player.id, row);
    }));
  }
  return totals.map(map => [...map.values()].map(row => ({ ...row, diff: row.actual - row.expected }))
    .sort((a, b) => a.diff - b.diff));
}

// The few swings worth naming for one team: up to two big misses and the biggest carry.
export function notableSwings(rows, threshold = 15) {
  return {
    cold: rows.filter(row => row.diff <= -threshold).slice(0, 2),
    hot: rows.filter(row => row.diff >= threshold).slice(-1),
  };
}

// How a manager got the player, from the optional public `acquired` field; unknown shapes show nothing.
export function acquiredLabel(acquired) {
  if (acquired?.how === 'draft' && Number.isInteger(acquired.round) && Number.isInteger(acquired.pick)) {
    return `Round ${acquired.round} · pick ${acquired.pick}`;
  }
  return acquired?.how === 'add' ? 'Waiver pickup' : acquired?.how === 'trade' ? 'Trade' : null;
}

// The league's biggest outperformers this week, on finished games only.
export function highlights(matchups, limit = 6, threshold = 15) {
  return matchups.filter(m => !m.unavailable)
    .flatMap(m => playerSwings(m).flatMap((rows, side) => rows.map(row => ({ ...row, team: [m.home, m.away][side], side, key: m.key }))))
    .filter(row => row.diff >= threshold)
    .sort((a, b) => b.diff - a.diff)
    .slice(0, limit);
}

// Why the season favorite leads.
export function seasonRead(rows) {
  if (!rows.length) return null;
  const leader = rows[0];
  const byWins = [...rows].sort((a, b) => b.expected_wins - a.expected_wins);
  const why = byWins[0].team.id === leader.team.id
    ? `Most projected wins (${leader.expected_wins})`
    : `Best playoff odds; ${byWins[0].team.name} projects more wins`;
  return { leader: leader.team.name, why };
}
