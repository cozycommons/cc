// Plain-English reads of the snapshot. Everything here is derived from published numbers.
const r = value => Math.round(value);
const list = names => (names.length < 2 ? names.join('') : `${names.slice(0, -1).join(', ')} and ${names.at(-1)}`);
const isLeft = day => day.state === 'projected' || (day.state === 'live' && !(Array.isArray(day.actual) && day.actual.some(Number.isFinite)));

// Games each side still has this week (projected days plus live days with no points yet).
export function gamesLeft(matchup) {
  return (matchup.days || []).filter(isLeft)
    .reduce((sum, day) => sum.map((value, side) => value + (Number.isFinite(day.games?.[side]) ? day.games[side] : 0)), [0, 0]);
}

// Why one side is favored this week, in one clause.
export function matchupReason(matchup) {
  const fav = matchup.chance >= 50 ? 0 : 1, other = 1 - fav;
  const names = [matchup.home.name, matchup.away.name];
  const lead = matchup.scores[fav] - matchup.scores[other];
  const left = gamesLeft(matchup), favLeft = left[fav], otherLeft = left[other];
  const odds = r(Math.max(matchup.chance, 100 - matchup.chance));
  const days = matchup.days || [];
  if (days.length && days.every(day => day.state === 'final')) {
    const [h, a] = matchup.scores.map(r);
    if (h === a) return `${names[0]} and ${names[1]} tie ${h}–${a}.`;
    return h > a ? `${names[0]} wins ${h}–${a}.` : `${names[1]} wins ${a}–${h}.`;
  }
  const volume = !favLeft && !otherLeft ? 'the last games still going' : favLeft > otherLeft ? `${favLeft} games left to ${otherLeft}` : favLeft < otherLeft ? `fewer games left (${favLeft} to ${otherLeft})` : `${favLeft} games left each`;
  if (lead > 0) return `${names[fav]} is ${odds}%: up ${r(lead)} with ${volume}.`;
  if (lead < 0) return `${names[fav]} is ${odds}% despite trailing by ${r(-lead)}: ${volume}.`;
  return `${names[fav]} is ${odds}%: tied, with ${volume}.`;
}

// Two or three sentences on the week: what's settled, what's close and why.
export function weekStory(matchups) {
  const live = matchups.filter(m => !m.unavailable);
  if (!live.length) return '';
  const favoriteName = m => (m.chance >= 50 ? m.home.name : m.away.name);
  const locks = live.filter(m => m.chance >= 90 || m.chance <= 10);
  const closest = [...live].sort((a, b) => Math.abs(a.chance - 50) - Math.abs(b.chance - 50))[0];
  const parts = [];
  if (locks.length) parts.push(`${list(locks.map(favoriteName))} ${locks.length === 1 ? 'is' : 'are'} all but done.`);
  if (Math.abs(closest.chance - 50) < 30) {
    parts.push(`Closest race: ${closest.home.name} vs ${closest.away.name}. ${matchupReason(closest)}`);
    const worst = playerSwings(closest).flat().sort((a, b) => a.diff - b.diff)[0];
    if (worst && worst.diff <= -20) parts.push(`${worst.name} is ${r(-worst.diff)} under expectation so far.`);
  }
  return parts.join(' ');
}

// Why the season favorite is the favorite, and how much the standings matter yet.
export function seasonStory(rows) {
  if (!rows.length) return '';
  const leader = rows[0];
  const byWins = [...rows].sort((a, b) => b.expected_wins - a.expected_wins);
  const played = rows.some(row => (row.record?.[0] || 0) + (row.record?.[1] || 0) + (row.record?.[2] || 0) > 0);
  const best = Math.max(...rows.map(row => row.playoff_pct));
  const why = byWins[0].team.id === leader.team.id
    ? `its roster projects for the most wins (${leader.expected_wins})`
    : `it is the likeliest to win a short playoff bracket, though ${byWins[0].team.name} projects for more wins`;
  const stage = played ? '' : ' Nobody has a result yet, so this is all roster strength.';
  const spread = best < 60 ? ` No team is better than ${r(best)}% to make the playoffs.` : '';
  return `${leader.team.name} leads because ${why}.${stage}${spread}`;
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

const swingText = row => `${row.name} ${r(row.actual)} vs ${r(row.expected)} expected`;

// One line per team: who dragged it down and who carried it, when the gap is meaningful.
export function swingLines(matchup, threshold = 15) {
  return playerSwings(matchup).map(rows => {
    const down = rows.filter(row => row.diff <= -threshold).slice(0, 2);
    const up = rows.filter(row => row.diff >= threshold).slice(-1);
    const parts = [];
    if (down.length) parts.push(`Below: ${down.map(swingText).join('; ')}`);
    if (up.length) parts.push(`Above: ${up.map(swingText).join('; ')}`);
    return parts.join('. ');
  });
}
