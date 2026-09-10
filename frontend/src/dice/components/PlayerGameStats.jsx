import React from 'react';
import PlayerAvatar from './PlayerAvatar.jsx';

const count = (value) => Number(value || 0);

export function playerGameMetrics(stats = {}) {
  const outcomes = stats.outcomes || {};
  const throws = ['miss', 'caught', 'point', 'sink', 'self_sink', 'fifa', 'invalid']
    .reduce((total, key) => total + count(outcomes[key]), 0);
  const tableHits = count(outcomes.caught) + count(outcomes.point) + count(outcomes.sink);
  return {
    throws,
    tableHits,
    tableHitRate: throws ? Math.round((tableHits / throws) * 100) : null,
    scoringThrows: count(outcomes.point) + count(outcomes.sink),
  };
}

const statChips = (stats = {}) => {
  const outcomes = stats.outcomes || {};
  return [
    [outcomes.point, 'point', 'points', 'var(--team1-color)'],
    [outcomes.sink, 'sink', 'sinks', 'var(--state-success)'],
    [outcomes.caught, 'table hit', 'table hits'],
    [stats.table_catches, 'catch', 'catches', 'var(--team2-color)'],
    [stats.fifa_goals, 'FIFA goal', 'FIFA goals', 'var(--accent-gold)'],
    [stats.fifa_kicks, 'FIFA kick', 'FIFA kicks', 'var(--accent-gold)'],
    [stats.fifa_catches, 'FIFA catch', 'FIFA catches', 'var(--accent-gold)'],
    [stats.fifa_saves, 'FIFA save', 'FIFA saves', 'var(--accent-gold)'],
    [outcomes.miss, 'miss', 'misses'],
    [outcomes.invalid, 'invalid', 'invalid'],
    [outcomes.self_sink, 'self-sink', 'self-sinks', 'var(--state-warning)'],
    [outcomes.fifa, 'FIFA allowed', 'FIFAs allowed', 'var(--state-warning)'],
  ].filter(([value]) => count(value) > 0).map(([value, singular, plural, color]) => ({
    value: count(value),
    label: count(value) === 1 ? singular : plural,
    color,
  }));
};

export default function PlayerGameStats({ teams, statsByPlayer, coverage = 'unknown', live = false }) {
  const allPlayers = teams.flatMap((team) => team.players);
  const observations = allPlayers.reduce(
    (total, player) => total + playerGameMetrics(statsByPlayer?.[player.user_id]).throws,
    0,
  );
  if (!statsByPlayer || observations === 0) return null;

  return (
    <section className="jk-card p-4 mt-3" aria-label="Player game stats">
      <div className="flex items-start justify-between gap-3">
        <div>
          <p className="jk-label">{live ? 'LIVE PLAYER STATS' : 'PLAYER STATS'}</p>
          <p className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>
            {observations} recorded throw{observations === 1 ? '' : 's'}
          </p>
        </div>
        <span className="jk-label px-2 py-1 rounded-full" style={{ background: 'var(--surface-sunken)', fontSize: 9 }}>
          {coverage === 'complete' ? 'Complete' : 'Recorded only'}
        </span>
      </div>

      <div className="mt-4 space-y-5">
        {teams.map((team, teamIndex) => (
          <div key={team.id}>
            <p className="jk-label mb-2" style={{ color: teamIndex === 0 ? 'var(--team1-color)' : 'var(--team2-color)' }}>
              {team.label || `Team ${teamIndex + 1}`}
            </p>
            <div className="space-y-2">
              {team.players.map((player) => {
                const stats = statsByPlayer[player.user_id] || {};
                const metrics = playerGameMetrics(stats);
                const chips = statChips(stats);
                return (
                  <div key={player.user_id} className="rounded-lg p-3" style={{ background: 'var(--surface-sunken)' }}>
                    <div className="flex items-center gap-3">
                      <PlayerAvatar profile={player} size={38} />
                      <div className="min-w-0 flex-1">
                        <p className="font-semibold text-sm truncate">{player.display_name}</p>
                        <p className="text-xs tabular-nums" style={{ color: 'var(--text-secondary)' }}>
                          {metrics.throws ? `${metrics.throws} throws · ${metrics.tableHitRate}% table rate` : 'No recorded throws'}
                        </p>
                      </div>
                    </div>
                    {chips.length > 0 && (
                      <div className="flex flex-wrap gap-1.5 mt-2.5">
                        {chips.map((chip) => (
                          <span key={chip.label} aria-label={`${chip.value} ${chip.label}`} className="px-2 py-1 rounded-full text-xs tabular-nums" style={{ background: 'var(--surface-card)', color: chip.color || 'var(--text-secondary)' }}>
                            <strong>{chip.value}</strong> {chip.label}
                          </span>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </div>
        ))}
      </div>

      {coverage !== 'complete' && (
        <p className="text-xs mt-4" style={{ color: 'var(--text-tertiary)' }}>
          Missing plays are excluded, not counted as misses.
        </p>
      )}
    </section>
  );
}
