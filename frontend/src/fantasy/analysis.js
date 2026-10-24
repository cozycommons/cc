// Short reads of the snapshot. Everything here is derived from published numbers.
const r = value => Math.round(value);
const isLeft = day => day.state === 'projected' || (day.state === 'live' && !(Array.isArray(day.actual) && day.actual.some(Number.isFinite)));
const finished = matchup => (matchup.days || []).length > 0 && matchup.days.every(day => day.state === 'final');

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
  if (!left[side] && !left[other]) facts.push('Last games in progress');
  else if (left[side] === left[other]) facts.push(`${left[side]} games left each`);
  else facts.push(`${left[side]} games left vs ${left[other]}`);
  return { side, headline: `${names[side]} ${r(Math.max(matchup.chance, 100 - matchup.chance))}%`, facts };
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

// The week in a few tagged lines: what's settled, what's close, who's cold and hot.
export function weekNotes(matchups) {
  const live = matchups.filter(m => !m.unavailable);
  if (!live.length) return [];
  const notes = [];
  const settled = live.filter(m => finished(m) || m.chance >= 90 || m.chance <= 10);
  if (settled.length) notes.push({ tone: 'lock', tag: 'Locked', text: settled.map(m => matchupRead(m).headline.replace(/ \d+%$| wins$/, '')).join(' · ') });
  const open = live.filter(m => !settled.includes(m));
  const closest = [...open].sort((a, b) => Math.abs(a.chance - 50) - Math.abs(b.chance - 50))[0];
  if (closest) {
    const read = matchupRead(closest);
    notes.push({ tone: 'close', tag: Math.abs(closest.chance - 50) <= 10 ? 'Coin flip' : 'Closest', key: closest.key,
      text: `${closest.home.name} vs ${closest.away.name}`, detail: `${read.headline} · ${read.facts.join(' · ')}` });
  }
  const players = live.flatMap(m => playerSwings(m).flatMap((rows, side) => rows.map(row => ({ ...row, team: [m.home, m.away][side].name }))));
  const cold = [...players].sort((a, b) => a.diff - b.diff)[0];
  const hot = [...players].sort((a, b) => b.diff - a.diff)[0];
  if (cold && cold.diff <= -20) notes.push({ tone: 'cold', tag: 'Cold', text: cold.name, detail: `${r(cold.actual)} of ${r(cold.expected)} expected · ${cold.team}` });
  if (hot && hot.diff >= 20) notes.push({ tone: 'hot', tag: 'Hot', text: hot.name, detail: `${r(hot.actual)} vs ${r(hot.expected)} expected · ${hot.team}` });
  return notes;
}

// Why the season favorite leads, plus short tags on how settled the race is.
export function seasonRead(rows) {
  if (!rows.length) return null;
  const leader = rows[0];
  const byWins = [...rows].sort((a, b) => b.expected_wins - a.expected_wins);
  const played = rows.some(row => (row.record?.[0] || 0) + (row.record?.[1] || 0) + (row.record?.[2] || 0) > 0);
  const best = Math.max(...rows.map(row => row.playoff_pct));
  const why = byWins[0].team.id === leader.team.id
    ? `Most projected wins (${leader.expected_wins})`
    : `Best playoff odds; ${byWins[0].team.name} projects more wins`;
  const tags = [];
  if (!played) tags.push('No games yet: roster strength only');
  if (best < 60) tags.push(`Wide open: nobody above ${r(best)}%`);
  return { leader: leader.team.name, why, tags };
}
