export function teamPlayers(game, team) {
  return (game.players || []).filter((p) => p.team === team);
}

export function teamAverageElo(game, team) {
  const players = teamPlayers(game, team);
  if (!players.length) return null;
  const withElo = players.filter((p) => p.elo_before != null);
  if (!withElo.length) return null;
  const sum = withElo.reduce((acc, p) => acc + p.elo_before, 0);
  return Math.round(sum / withElo.length);
}

export function formatDate(dateString) {
  const d = new Date(dateString);
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
}

export function formatDateTime(dateString) {
  const d = new Date(dateString);
  return d.toLocaleString(undefined, {
    month: 'short',
    day: 'numeric',
    hour: 'numeric',
    minute: '2-digit',
  });
}

export function canEditGame(game, user, isAdmin) {
  if (!user) return false;
  if (isAdmin) return true;
  if (game.created_by === user.id) return true;
  return (game.players || []).some((p) => p.user_id === user.id);
}

export function canEditTournament(tournament, user, isAdmin) {
  if (!user) return false;
  if (isAdmin) return true;
  return (tournament.hosts || []).some((h) => h.user_id === user.id);
}

export function isEnrolled(tournament, user) {
  if (!user) return false;
  return (tournament.enrolled_players || []).some((p) => p.user_id === user.id);
}

export function hasDuplicatePlayerIds(...teams) {
  const filled = teams.flat().filter(Boolean);
  return new Set(filled).size !== filled.length;
}

// Win/loss standings derived purely from the tournament's completed games —
// no separate persisted state. Enrolled players who haven't played yet still
// show up at 0-0; anyone who played but isn't (or is no longer) enrolled
// shows up too, since their record is real regardless.
export function computeTournamentStandings(tournament) {
  const records = new Map();
  const ensure = (profile) => {
    if (!records.has(profile.user_id)) {
      records.set(profile.user_id, {
        user_id: profile.user_id,
        display_name: profile.display_name,
        avatar_url: profile.avatar_url,
        wins: 0,
        losses: 0,
        self_sinks: 0,
      });
    }
    return records.get(profile.user_id);
  };

  (tournament.enrolled_players || []).forEach(ensure);
  (tournament.completed_games || []).forEach((game) => {
    (game.players || []).filter((p) => p.counts_for_group_stage !== false).forEach((p) => {
      const record = ensure(p);
      if (p.team === game.winner_team) record.wins += 1;
      else record.losses += 1;
      record.self_sinks += p.self_sinks || 0;
    });
  });

  return Array.from(records.values()).sort((a, b) => {
    if (a.wins !== b.wins) return b.wins - a.wins;
    if (a.losses !== b.losses) return a.losses - b.losses;
    // Jaycee wins any tiebreak, e.g. tied for 1st-3rd.
    if (a.display_name === 'Jaycee' && b.display_name !== 'Jaycee') return -1;
    if (b.display_name === 'Jaycee' && a.display_name !== 'Jaycee') return 1;
    return a.display_name.localeCompare(b.display_name);
  });
}
