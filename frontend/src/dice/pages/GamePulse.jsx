import React, { useMemo } from 'react';
import { Link } from 'react-router-dom';
import { Line, LineChart, ReferenceLine, ResponsiveContainer, XAxis, YAxis } from 'recharts';
import PlayerAvatar from '../components/PlayerAvatar.jsx';

const wholePercent = (value) => `${Math.round(Number(value) * 100)}%`;

function teamName(game, teamId) {
  return (game.teams?.[teamId] || [])
    .map((playerId) => game.player_names?.[playerId] || String(playerId).slice(-4))
    .join(' + ') || teamId;
}

function momentText(point, game) {
  if (!point || point.kind === 'start') return 'Pregame odds';
  const [left, right] = game.team_order;
  const favored = point.swing >= 0 ? left : right;
  const amount = Math.round(Math.abs(point.swing) * 100);
  const fifaActor = point.fifa_actor_id && (game.player_names?.[point.fifa_actor_id] || String(point.fifa_actor_id).slice(-4));
  const player = fifaActor || (point.thrower_id && (game.player_names?.[point.thrower_id] || String(point.thrower_id).slice(-4)));
  const result = point.outcome?.replaceAll('_', ' ');
  if (point.kind === 'reopen') return `Reopened · ${point.score.join('–')}`;
  if (point.kind === 'correction') {
    return player && result
      ? `${player.split(' ')[0]} corrected to ${result} · ${point.score.join('–')}`
      : `Correction · ${point.score.join('–')}`;
  }
  if (point.kind === 'finish') return `Final · ${point.score.join('–')}`;
  if (point.kind === 'retoss') return 'Retoss · old throw removed';
  if (point.kind === 'score_update') {
    return amount ? `Score update · ${teamName(game, favored)} +${amount}%` : `Score · ${point.score.join('–')}`;
  }
  if (point.outcome === 'fifa' && fifaActor) {
    const action = ({ goal: 'scored a FIFA goal', kick_catch: 'caught the FIFA', goal_saved: 'saved the FIFA' })[point.fifa_finish] || 'made a FIFA play';
    const story = `${fifaActor.split(' ')[0]} ${action}`;
    return amount ? `${story} · ${teamName(game, favored)} +${amount}%` : story;
  }
  if (player && result && amount) return `${player.split(' ')[0]} ${result} · ${teamName(game, favored)} +${amount}%`;
  if (player && result) return `${player.split(' ')[0]} · ${result}`;
  return point.score.join('–');
}

function pickSummary(pick, game) {
  if (!pick) return null;
  const selection = teamName(game, pick.selection);
  if (pick.status === 'won') return { headline: `WON +${pick.potential_return - pick.stake} DICE`, detail: `${pick.potential_return} back` };
  if (pick.status === 'lost') return { headline: `LOST ${pick.stake} DICE`, detail: selection };
  if (pick.status === 'void') return { headline: 'PICK VOID', detail: `${pick.stake} Dice returned` };
  return {
    headline: `YOUR PICK · ${selection}`,
    detail: `${pick.stake} at ${wholePercent(pick.locked_probability_millionths / 1_000_000)} · ${pick.potential_return} back`,
  };
}

function pickColor(status) {
  if (status === 'won') return 'var(--state-success)';
  if (status === 'lost') return 'var(--state-danger)';
  if (status === 'void') return 'var(--state-warning)';
  return 'var(--text-primary)';
}

export default function GamePulse({ game, pulse }) {
  const chart = useMemo(() => (pulse?.points || []).map((point) => ({
    ...point,
    chance: Number(point.team1_win_probability) * 100,
  })), [pulse]);
  if (!pulse || chart.length === 0) return null;

  const latest = chart.at(-1);
  const previous = chart.at(-2);
  const moment = [...chart].reverse().find((point) => point.kind !== 'start');
  const [left, right] = game.team_order;
  const wager = pickSummary(pulse.virtual?.pick, game);
  const reducedMotion = globalThis.matchMedia?.('(prefers-reduced-motion: reduce)').matches === true;

  const playerProfile = (playerId) => ({
    user_id: playerId,
    display_name: game.player_names?.[playerId] || String(playerId).slice(-4),
    avatar_url: game.player_avatars?.[playerId] || null,
  });
  const movement = (key) => previous ? Math.round((Number(latest[key]) - Number(previous[key])) * 100) : 0;

  return (
    <section className="jk-card p-4" aria-label="Win chance history">
      <div className="flex items-center justify-between gap-3">
        <p className="jk-label">WIN CHANCE</p>
        <p className="jk-label">{game.status === 'completed' ? 'FINAL' : 'LIVE'}</p>
      </div>
      <div className="grid grid-cols-2 gap-3 mt-3">
        {[[left, 'team1_win_probability'], [right, 'team2_win_probability']].map(([teamId, key], index) => {
          const delta = movement(key);
          return (
            <div key={teamId} className={index ? 'min-w-0 text-right' : 'min-w-0'}>
              <div className={`flex items-center gap-2 ${index ? 'justify-end flex-row-reverse' : ''}`}>
                <div className="flex -space-x-2" aria-hidden="true">
                  {game.teams[teamId].map((playerId) => (
                    <span key={playerId} className="rounded-full ring-2 ring-[var(--surface-card)]">
                      <PlayerAvatar profile={playerProfile(playerId)} size={28} linkToProfile={false} />
                    </span>
                  ))}
                </div>
                <p className="text-xs font-semibold truncate">{game.teams[teamId].map((id) => playerProfile(id).display_name.split(' ')[0]).join(' & ')}</p>
              </div>
              <div className={`min-w-0 flex flex-wrap items-center gap-x-2 gap-y-1 mt-1 ${index ? 'justify-end' : ''}`}>
                <p key={`${key}-${latest.match_version}`} className="jk-display jk-pulse-number text-3xl tabular-nums">{wholePercent(latest[key])}</p>
                {delta !== 0 && (
                  <span
                    className="rounded-full px-2 py-1 text-xs font-semibold tabular-nums whitespace-nowrap jk-pulse-number"
                    aria-label={`${teamName(game, teamId)} ${delta > 0 ? 'up' : 'down'} ${Math.abs(delta)} percentage points`}
                    style={{ color: delta > 0 ? 'var(--state-success)' : 'var(--state-danger)', background: 'var(--surface-sunken)' }}
                  >{delta > 0 ? '↑' : '↓'} {Math.abs(delta)}%</span>
                )}
              </div>
            </div>
          );
        })}
      </div>
      <div
        className="h-20 mt-2"
        role="img"
        aria-label={`${teamName(game, left)} win chance moved from ${wholePercent(chart[0].team1_win_probability)} to ${wholePercent(latest.team1_win_probability)}`}
      >
        <ResponsiveContainer width="100%" height="100%" minWidth={0}>
          <LineChart data={chart} margin={{ top: 8, right: 4, bottom: 4, left: 4 }}>
            <XAxis dataKey="match_version" hide />
            <YAxis domain={[0, 100]} hide />
            <ReferenceLine y={50} stroke="var(--border-subtle)" strokeDasharray="4 4" />
            <Line
              dataKey="chance"
              type="monotone"
              stroke="var(--team1-color)"
              strokeWidth={3}
              dot={false}
              activeDot={{ r: 4 }}
              isAnimationActive={!reducedMotion}
              animationDuration={450}
            />
          </LineChart>
        </ResponsiveContainer>
      </div>
      <p className="text-sm font-medium mt-1">{momentText(moment, game)}</p>
      <p className="text-xs mt-1" style={{ color: 'var(--text-tertiary)' }}>Ratings + live score</p>

      {wager && (
        <div key={pulse.virtual.pick.status} className="jk-pulse-result mt-3 pt-3" style={{ borderTop: '1px solid var(--border-subtle)' }}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="jk-label" style={{ color: pickColor(pulse.virtual.pick.status) }}>{wager.headline}</p>
              <p className="text-xs mt-1" style={{ color: 'var(--text-secondary)' }}>{wager.detail}</p>
            </div>
            {pulse.virtual.balance !== null && (
              <div className="text-right shrink-0">
                <p className="font-semibold tabular-nums">{pulse.virtual.balance} Dice</p>
                {pulse.virtual.rank && <p className="text-xs" style={{ color: 'var(--text-tertiary)' }}>#{pulse.virtual.rank} of {pulse.virtual.field_size}</p>}
              </div>
            )}
          </div>
          <Link to={`/dice/tournament/${pulse.virtual.tournament_id}/virtual`} className="inline-block mt-2 text-xs underline">
            Dice & standings
          </Link>
        </div>
      )}
    </section>
  );
}
