import { playerGameMetrics } from './components/PlayerGameStats.jsx';

const OUTCOMES = ['miss', 'caught', 'point', 'sink', 'self_sink', 'fifa', 'invalid'];
const ROLES = ['table_catches', 'fifa_goals', 'fifa_kicks', 'fifa_catches', 'fifa_saves'];
const count = (value) => Number(value || 0);

export function aggregateRecordedStats(games = []) {
  const players = new Map();
  let recordedGames = 0;
  let completeGames = 0;

  games.forEach((game) => {
    const recorded = game.recorded_stats;
    if (!recorded?.players || count(recorded.observations) < 1) return;
    recordedGames += 1;
    if (recorded.coverage === 'complete') completeGames += 1;
    const profiles = new Map((game.players || []).map((player) => [player.user_id, player]));

    Object.entries(recorded.players).forEach(([userId, stats]) => {
      const profile = profiles.get(userId) || {};
      const aggregate = players.get(userId) || {
        user_id: userId,
        display_name: profile.display_name || 'Unknown player',
        avatar_url: profile.avatar_url || null,
        gamesRecorded: 0,
        outcomes: Object.fromEntries(OUTCOMES.map((key) => [key, 0])),
        ...Object.fromEntries(ROLES.map((key) => [key, 0])),
      };
      aggregate.display_name = profile.display_name || aggregate.display_name;
      aggregate.avatar_url = profile.avatar_url || aggregate.avatar_url;
      aggregate.gamesRecorded += 1;
      OUTCOMES.forEach((key) => { aggregate.outcomes[key] += count(stats?.outcomes?.[key]); });
      ROLES.forEach((key) => { aggregate[key] += count(stats?.[key]); });
      players.set(userId, aggregate);
    });
  });

  const rankedPlayers = [...players.values()].map((player) => {
    const metrics = playerGameMetrics(player);
    return {
      ...player,
      ...metrics,
      points: count(player.outcomes.point),
      sinks: count(player.outcomes.sink),
      misses: count(player.outcomes.miss),
      catches: count(player.table_catches) + count(player.fifa_catches),
      fifaActions: count(player.fifa_goals) + count(player.fifa_kicks) + count(player.fifa_catches) + count(player.fifa_saves),
    };
  }).filter((player) => player.throws > 0 || player.catches > 0 || player.fifaActions > 0)
    .sort((left, right) => right.throws - left.throws || left.display_name.localeCompare(right.display_name));

  return {
    players: rankedPlayers,
    recordedGames,
    completeGames,
    observations: rankedPlayers.reduce((total, player) => total + player.throws, 0),
  };
}

export function metricLeaders(players, key, { minimumThrows = 0 } = {}) {
  const eligible = [...players]
    .filter((player) => player.throws >= minimumThrows && Number(player[key]) > 0)
    .sort((left, right) => Number(right[key]) - Number(left[key]) || right.throws - left.throws || left.display_name.localeCompare(right.display_name));
  if (!eligible.length) return [];
  return eligible.filter((player) => Number(player[key]) === Number(eligible[0][key]));
}

export function metricLeader(players, key, options) {
  return metricLeaders(players, key, options)[0] || null;
}
