import React, { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { diceApi } from '../api.js';
import PlayerAvatar from '../components/PlayerAvatar.jsx';
import GamePulse from './GamePulse.jsx';
import LiveGameActionSheet from './LiveGameActionSheet.jsx';
import LiveScoringControls from './LiveScoringControls.jsx';
import { deriveLiveTurn } from '../liveTurnOrder.js';

const resultLabel = (event) => {
  if (event.outcome === 'fifa') {
    return {
      goal: 'FIFA goal',
      kick_catch: 'FIFA catch',
      goal_saved: 'FIFA saved',
    }[event.fifa?.finish] || 'FIFA';
  }
  return { caught: 'table hit' }[event.outcome]
    || event.outcome || event.kind.replaceAll('_', ' ');
};
const shortId = (value) => {
  const text = String(value || '');
  return text.split('-').length === 5 ? text.slice(-4) : text.split('-')[0];
};
const commandId = () => globalThis.crypto?.randomUUID?.() || `live-${Date.now()}`;

function formatLiveDuration(createdAt, now) {
  const started = Date.parse(createdAt);
  if (!Number.isFinite(started)) return '0:00';
  const elapsed = Math.max(0, Math.floor((now - started) / 1000));
  return `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`;
}

function LiveOddsMeter({ game, prediction, interactive, onOpen }) {
  if (prediction?.status !== 'available') return null;
  const [left, right] = game.team_order;
  const leftPercent = Math.round(Number(prediction.team1_win_probability) * 100);
  const rightPercent = Math.round(Number(prediction.team2_win_probability) * 100);
  const teamName = (teamId) => game.teams[teamId]
    .map((playerId) => game.player_names?.[playerId]?.split(' ')[0] || shortId(playerId))
    .join(' & ');
  const content = <>
    <span className="flex justify-between gap-3 text-xs font-semibold tabular-nums">
      <span>{leftPercent}%</span>
      <span>{rightPercent}%</span>
    </span>
    <span className="jk-live-odds-track mt-1.5" aria-hidden="true">
      <span className="jk-live-odds-left" style={{ width: `${leftPercent}%` }} />
      <span className="jk-live-odds-right" />
    </span>
  </>;
  const label = `${teamName(left)} ${leftPercent} percent, ${teamName(right)} ${rightPercent} percent${interactive ? '. Open stats' : ''}`;

  return interactive ? (
    <button type="button" className="jk-live-odds-meter mt-3" aria-label={label} onClick={onOpen}>
      {content}
    </button>
  ) : (
    <div className="jk-live-odds-meter mt-3" role="img" aria-label={label}>{content}</div>
  );
}

const receiptMessage = (command, accepted, playerLabel, events) => {
  const score = accepted.projection.score.join('–');
  const player = command.thrower_id ? playerLabel(command.thrower_id) : '';
  const target = events.find((event) => event.id === command.target_event_id);
  const outcome = {
    point: 'scored',
    miss: 'missed',
    caught: 'hit the table',
    sink: 'sank it',
    self_sink: 'self-sank',
    invalid: 'invalid throw',
  }[command.outcome];

  switch (command.kind) {
    case 'record_throw':
      if (command.outcome === 'fifa') {
        if (command.fifa.finish === 'goal_saved') return `${playerLabel(command.fifa.saver_id)} saved the FIFA · ${score}`;
        if (command.fifa.finish === 'kick_catch') return `${playerLabel(command.fifa.catcher_id)} caught the FIFA · ${score}`;
        return `${playerLabel(command.fifa.kicker_id)} scored a FIFA goal · ${score}`;
      }
      return `${player} ${outcome || command.outcome.replaceAll('_', ' ')} · ${score}`;
    case 'change_throw':
      return `Changed ${target ? resultLabel(target) : 'result'} → ${command.outcome.replaceAll('_', ' ')} · ${score}`;
    case 'remove_mistake':
      return `Removed ${target ? `${playerLabel(target.thrower_id)}’s ${resultLabel(target)}` : 'result'} · ${score}`;
    case 'retoss':
      return `Retoss · old throw removed · ${score}`;
    case 'fix_score':
      return `Score caught up · ${score}`;
    case 'finish':
      return `Final · ${score}`;
    case 'off_roof':
      return `Off roof · ${score}`;
    case 'reopen':
      return `Game reopened · ${score}`;
    case 'undo_last':
      return `Undid ${target ? `${playerLabel(target.thrower_id)}’s ${resultLabel(target)}` : 'last result'} · ${score}`;
    default:
      return `Saved · ${score}`;
  }
};

export default function LiveGame({ auth }) {
  const { matchId } = useParams();
  const enabled = auth.features?.dice_live_referee?.effective === true;
  const [game, setGame] = useState(null);
  const [prediction, setPrediction] = useState(null);
  const [pulse, setPulse] = useState(null);
  const [thrower, setThrower] = useState('');
  const [receipt, setReceipt] = useState(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [liveMode, setLiveMode] = useState('referee');
  const [actionTarget, setActionTarget] = useState(null);
  const [recovery, setRecovery] = useState(null);
  const [terminalAction, setTerminalAction] = useState('');
  const [clock, setClock] = useState(Date.now());
  const latestVersion = useRef(0);
  const latestTurnHistory = useRef('');

  const load = useCallback(async (minimumVersion = 0) => {
    if (!enabled || !auth.token) return;
    setError('');
    try {
      const canonical = await diceApi.getLiveGame(auth.token, matchId);
      if (canonical.version < minimumVersion || canonical.version < latestVersion.current) return;
      latestVersion.current = canonical.version;
      setGame(canonical);
      const turn = deriveLiveTurn(canonical);
      if (turn.historyKey !== latestTurnHistory.current) {
        latestTurnHistory.current = turn.historyKey;
        setThrower(turn.nextThrowerId);
      } else {
        setThrower((current) => current || turn.nextThrowerId || '');
      }
      let pulseLoaded = false;
      if (typeof diceApi.getLivePulse === 'function') {
        try {
          const story = await diceApi.getLivePulse(auth.token, matchId);
          if (story.match_version === canonical.version) {
            const latest = story.points.at(-1);
            setPulse(story);
            setPrediction(latest ? {
              status: 'available', match_version: story.match_version,
              team1_win_probability: latest.team1_win_probability,
              team2_win_probability: latest.team2_win_probability,
              pregame_source: story.pregame_source,
              pregame_model_id: story.pregame_model_id,
              pregame_model_version: story.pregame_model_version,
              input_timestamp: story.input_timestamp,
            } : null);
            pulseLoaded = true;
          } else {
            setPulse(null);
          }
        } catch { setPulse(null); }
      }
      if (!pulseLoaded && typeof diceApi.getLivePrediction === 'function') {
        try {
          const estimate = await diceApi.getLivePrediction(auth.token, matchId);
          setPrediction(estimate?.match_version === canonical.version ? estimate : null);
        } catch { setPrediction(null); }
      }
    } catch (requestError) {
      setError(requestError.message || 'Could not load this live game.');
    }
  }, [auth.token, enabled, matchId]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (!game || game.status === 'completed') return undefined;
    const timer = window.setInterval(() => setClock(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, [game]);

  useEffect(() => {
    if (!receipt) return undefined;
    const timer = window.setTimeout(() => setReceipt(null), 5000);
    return () => window.clearTimeout(timer);
  }, [receipt]);

  // Other referees can append events while this screen is open. Refresh the
  // canonical projection periodically, but stop once the game is complete.
  const gameLifecycle = game?.status;
  useEffect(() => {
    if (!enabled || !auth.token || !gameLifecycle || gameLifecycle === 'completed') return undefined;
    const timer = window.setInterval(() => load(), 15000);
    return () => window.clearInterval(timer);
  }, [auth.token, enabled, gameLifecycle, load]);

  const roster = useMemo(() => game
    ? game.team_order.flatMap((teamId) => game.teams[teamId].map((playerId) => ({ teamId, playerId })))
    : [], [game]);
  const turnHint = useMemo(() => deriveLiveTurn(game), [game]);
  const joined = game?.referees.some((referee) => referee.user_id === auth.user?.id && !referee.left_at);
  const pendingRetoss = useMemo(() => {
    if (!game) return null;
    return [...game.events].reverse().find((event) => event.kind === 'retoss_decision'
      && !game.events.some((candidate) => candidate.replay_of === event.id
        || (candidate.kind === 'correction' && candidate.target_event_id === event.id))) || null;
  }, [game]);

  const executeCommand = async (command) => {
    if (!game || saving) return;
    setSaving(true);
    setError('');
    try {
      const accepted = await diceApi.sendLiveCommand(auth.token, matchId, command);
      setReceipt({
        message: receiptMessage(command, accepted, playerLabel, game.events),
        undoSequence: command.kind === 'record_throw' ? accepted.last_sequence : null,
      });
      setRecovery(null);
      setGame((current) => ({
        ...current,
        version: accepted.accepted_version,
        score: accepted.projection.score,
        status: accepted.projection.status,
        detail_coverage: accepted.projection.coverage,
        projection: accepted.projection,
      }));
      latestVersion.current = accepted.accepted_version;
      await load(accepted.accepted_version);
      setActionTarget(null);
      setTerminalAction('');
    } catch (requestError) {
      if (requestError.status === 409 && requestError.detail?.code === 'dice_live.stale_version') {
        const canonical = await diceApi.getLiveGame(auth.token, matchId);
        const change = canonical.events.slice(game.events.length).at(-1);
        setGame(canonical);
        setRecovery({ type: 'stale', command, change });
        setError('Another referee changed the canonical game. Review it before resubmitting.');
      } else if (!requestError.status) {
        setRecovery({ type: 'ambiguous', command });
        setError('Delivery was unclear. Retry the exact command ID to avoid a duplicate.');
      } else {
        setError(requestError.message || 'The result was not accepted.');
      }
    } finally {
      setSaving(false);
    }
  };

  const sendCommand = (fields) => executeCommand({
    client_command_id: commandId(), expected_version: game.version, match_elapsed_ms: 0, ...fields,
  });

  const record = (outcome) => sendCommand({
    kind: 'record_throw',
    thrower_id: pendingRetoss?.thrower_id || thrower,
    outcome,
    ...(pendingRetoss ? { replay_of: pendingRetoss.id } : {}),
  });

  const openCorrection = (event) => {
    setActionTarget(event);
  };

  const intentLabel = recovery && [recovery.command.kind.replaceAll('_', ' '), recovery.command.outcome, recovery.command.thrower_id && shortId(recovery.command.thrower_id)].filter(Boolean).join(' · ');
  const terminalEvent = game?.events && [...game.events].reverse().find((event) => ['completion', 'off_roof'].includes(event.kind));
  const correctedEventIds = new Set(game?.events.filter((event) => event.kind === 'correction').map((event) => event.target_event_id));
  const retossedEventIds = new Set(game?.events.filter((event) => event.kind === 'retoss_decision' && !correctedEventIds.has(event.id)).map((event) => event.target_event_id));
  const eventSequence = new Map(game?.events.map((event) => [event.id, event.sequence]) || []);
  const eventDisposition = (event) => {
    if (event.kind === 'correction') return `Corrected throw #${eventSequence.get(event.target_event_id) || '?'}`;
    if (event.kind === 'retoss_decision') return `Retoss requested for throw #${eventSequence.get(event.target_event_id) || '?'}`;
    if (correctedEventIds.has(event.id)) return 'Corrected';
    if (retossedEventIds.has(event.id)) return 'Retossed';
    if (event.replacement_for && correctedEventIds.has(event.replacement_for)) return 'Replacement';
    return null;
  };
  const receiptUndoTarget = receipt?.undoSequence && game?.events.find((event) => (
    event.sequence === receipt.undoSequence
    && event.kind === 'observation'
    && !correctedEventIds.has(event.id)
    && !retossedEventIds.has(event.id)
  ));
  const statLabels = [
    ['point', 'Points'], ['caught', 'Caught'], ['sink', 'Sinks'], ['self_sink', 'Self-sinks'],
    ['fifa', 'FIFA'], ['invalid', 'Invalid'], ['miss', 'Misses'],
  ];
  const stats = game?.projection?.stats || {};
  const playerStats = game?.projection?.player_stats || {};
  const playerLabel = (playerId) => game?.player_names?.[playerId] || shortId(playerId);
  const playerProfile = (playerId) => ({
    user_id: playerId,
    display_name: playerLabel(playerId),
    avatar_url: game?.player_avatars?.[playerId] || null,
  });
  const compactPlayerLabel = (playerId) => playerLabel(playerId).split(' ')[0];
  const playerStatLabels = [
    ['point', 'point', 'points'], ['sink', 'sink', 'sinks'], ['self_sink', 'self-sink', 'self-sinks'],
    ['caught', 'throw caught', 'throws caught'], ['miss', 'miss', 'misses'],
    ['invalid', 'invalid throw', 'invalid throws'], ['fifa', 'FIFA against', 'FIFA against'],
  ];
  const summarizePlayer = (playerId) => {
    const player = playerStats[playerId];
    if (!player) return [];
    const summary = playerStatLabels
      .filter(([key]) => Number(player.outcomes?.[key]) > 0)
      .map(([key, singular, plural]) => {
        const count = Number(player.outcomes[key]);
        return `${count} ${count === 1 ? singular : plural}`;
      });
    if (Number(player.fifa_goals) > 0) summary.push(`${player.fifa_goals} FIFA goal${player.fifa_goals === 1 ? '' : 's'}`);
    if (Number(player.fifa_kicks) > 0) summary.push(`${player.fifa_kicks} FIFA kick${player.fifa_kicks === 1 ? '' : 's'}`);
    if (Number(player.fifa_catches) > 0) summary.push(`${player.fifa_catches} FIFA catch${player.fifa_catches === 1 ? '' : 'es'}`);
    if (Number(player.fifa_saves) > 0) summary.push(`${player.fifa_saves} FIFA save${player.fifa_saves === 1 ? '' : 's'}`);
    return summary;
  };
  const recentPlays = game?.events.filter((event) => event.kind === 'observation').slice(-5).reverse() || [];
  const gameStatus = game?.status === 'completed' ? 'Final' : game?.status === 'ready_to_finish' ? 'Ready to finish' : 'In progress';
  const hasRecordedStats = Object.values(stats).some((count) => Number(count) > 0);
  const aggregateStatsCard = hasRecordedStats && (
    <section className="jk-card p-4 mt-3" aria-label="Recorded live stats">
      <p className="jk-label">GAME STATS</p>
      <div className="grid grid-cols-2 gap-x-4 gap-y-2 mt-3 text-sm">
        {statLabels.filter(([key]) => Number(stats[key]) > 0).map(([key, label]) => (
          <div key={key} className="flex justify-between gap-3">
            <span>{label}</span><span className="font-semibold tabular-nums">{stats[key]}</span>
          </div>
        ))}
      </div>
      {game?.detail_coverage !== 'complete' && <p className="text-xs mt-3" style={{ color: 'var(--text-tertiary)' }}>Recorded plays only.</p>}
    </section>
  );

  if (!enabled) {
    return (
      <main className="max-w-xl mx-auto px-4 py-12 text-center">
        <div className="jk-card p-6">
          <p className="jk-label">// LIVE REFEREE</p>
          <h1 className="jk-display text-3xl mt-2">Live referee unavailable</h1>
          <p className="mt-3 text-sm" style={{ color: 'var(--text-secondary)' }}>No live game data was requested.</p>
          <Link to="/dice" className="inline-block mt-5 underline">Back to Dice</Link>
        </div>
      </main>
    );
  }

  if (!game) {
    return (
      <main className="max-w-xl mx-auto px-4 py-12">
        <p className="jk-label text-center">{error || 'Loading game…'}</p>
      </main>
    );
  }

  const [left, right] = game.team_order;
  return (
    <main className="max-w-xl mx-auto px-4 pt-5 pb-32">
      <div className="flex items-center justify-between gap-3 mb-4">
        <Link to="/dice/live" className="text-sm underline">Live games</Link>
        <button type="button" className="jk-label underline" onClick={() => load()}>Reload</button>
      </div>

      <div className="sticky top-2 z-10">
      <section
        className="jk-card jk-live-scoreboard p-5 text-center overflow-hidden"
        style={{
          background: 'linear-gradient(90deg, color-mix(in srgb, var(--team1-color) 10%, var(--surface-card)) 0 50%, color-mix(in srgb, var(--team2-color) 10%, var(--surface-card)) 50% 100%)',
        }}
      >
        <div className="flex justify-between gap-3 text-xs font-semibold">
          {[left, right].map((teamId, teamIndex) => (
            <div key={teamId} className={`flex items-center gap-2 min-w-0 max-w-[46%] ${teamIndex === 1 ? 'flex-row-reverse text-right' : ''}`}>
              <div className="flex -space-x-2 shrink-0" aria-hidden="true">
                {game.teams[teamId].map((playerId) => (
                  <span key={playerId} className="rounded-full ring-2 ring-[var(--surface-card)]">
                    <PlayerAvatar profile={playerProfile(playerId)} size={28} linkToProfile={false} />
                  </span>
                ))}
              </div>
              <span className="truncate" style={{ color: 'var(--text-primary)' }}>
                {game.teams[teamId].map(compactPlayerLabel).join(' & ')}
              </span>
            </div>
          ))}
        </div>
        <p key={game.version} className="jk-display jk-live-score jk-live-score-value tabular-nums mt-2">
          {game.score[0]}–{game.score[1]}
        </p>
        <LiveOddsMeter
          game={game}
          prediction={prediction}
          interactive={joined && game.status !== 'completed'}
          onOpen={() => setLiveMode('stats')}
        />
        <p className="jk-live-status mt-3 jk-label"><span>{gameStatus}</span> · {formatLiveDuration(game.created_at, clock)}</p>
      </section>

      {joined && game.status !== 'completed' && (
        <div className="jk-live-mode-switch mt-2" role="group" aria-label="Live game view">
          <button
            type="button"
            aria-pressed={liveMode === 'referee'}
            onClick={() => setLiveMode('referee')}
          >
            Referee
          </button>
          <button
            type="button"
            aria-pressed={liveMode === 'stats'}
            onClick={() => setLiveMode('stats')}
          >
            Stats
          </button>
        </div>
      )}
      </div>

      {(game.status === 'completed' || !joined || liveMode === 'stats') && pulse && (
        <div
          role={joined && game.status !== 'completed' ? 'region' : undefined}
          aria-label={joined && game.status !== 'completed' ? 'Stats view' : undefined}
          className="jk-live-mode-panel mt-3"
        >
          <GamePulse game={game} pulse={pulse} />
        </div>
      )}

      {(game.status === 'completed' || !joined || liveMode === 'stats') && !pulse && prediction?.status === 'available' && (
        <section
          role={joined && game.status !== 'completed' ? 'region' : undefined}
          className="jk-card jk-live-mode-panel p-4 mt-3"
          aria-label={joined && game.status !== 'completed' ? 'Stats view' : 'Live win prediction'}
        >
          <p className="jk-label">{game.status === 'completed' ? 'FINAL WIN RESULT' : 'WIN CHANCE'}</p>
          <div className="flex gap-2 mt-3 h-3" aria-hidden="true">
            <div className="rounded-l-full" style={{ width: `${prediction.team1_win_probability * 100}%`, background: 'var(--team1-color)' }} />
            <div className="rounded-r-full flex-1" style={{ background: 'var(--team2-color)' }} />
          </div>
          <div className="flex justify-between mt-2 text-sm font-semibold tabular-nums">
            <span>{Math.round(prediction.team1_win_probability * 100)}%</span>
            <span>{Math.round(prediction.team2_win_probability * 100)}%</span>
          </div>
          <p className="text-xs mt-2" style={{ color: 'var(--text-tertiary)' }}>
            {prediction.pregame_source === 'independent_model_snapshot'
              ? `Based on pregame win-rate model ${prediction.pregame_model_version || ''} and the current score`
              : prediction.pregame_source === 'legacy_elo_snapshot'
                ? 'Based on the match’s saved rating snapshot and the current score'
                : 'Based on the current score'}
          </p>
        </section>
      )}

      {joined && game.status !== 'completed' && liveMode === 'stats' && !pulse && prediction?.status !== 'available' && (
        <section role="region" aria-label="Stats view" className="jk-card jk-live-mode-panel p-5 mt-3 text-center">
          <p className="jk-label">WIN CHANCE UNAVAILABLE</p>
          <p className="text-sm mt-2" style={{ color: 'var(--text-secondary)' }}>Recorded plays are still shown below.</p>
        </section>
      )}

      {receipt && (
        <div className="jk-live-receipt-shell" role="status">
          <div className="jk-live-receipt px-4 py-3 rounded-lg text-sm font-semibold">
            <span className="min-w-0 truncate">{receipt.message}</span>
            {receiptUndoTarget && (
              <button
                type="button"
                className="shrink-0"
                disabled={saving}
                onClick={() => sendCommand({ kind: 'undo_last', target_event_id: receiptUndoTarget.id, reason: 'mistaken_entry' })}
              >Undo</button>
            )}
          </div>
        </div>
      )}
      {error && <p role="alert" className="mt-3 p-3 text-sm rounded-md" style={{ color: 'var(--state-danger)', background: 'var(--surface-sunken)' }}>{error}</p>}

      {game.status === 'completed' && Object.keys(playerStats).length > 0 && (
        <section className="jk-card p-4 mt-3" aria-label="Player game stats">
          <p className="jk-label">RECORDED PLAYS</p>
          <div className="mt-3 space-y-4">
            {game.team_order.map((teamId) => (
              <div key={teamId}>
                <p className="text-xs font-semibold" style={{ color: 'var(--text-secondary)' }}>
                  {game.teams[teamId].map(playerLabel).join(' + ')}
                </p>
                <div className="mt-1">
                  {game.teams[teamId].map((playerId) => {
                    const summary = summarizePlayer(playerId);
                    return (
                      <div key={playerId} className="py-2 flex items-start justify-between gap-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
                        <span className="font-semibold text-sm">{playerLabel(playerId)}</span>
                        <span className="text-xs text-right" style={{ color: 'var(--text-secondary)' }}>
                          {summary.length ? summary.join(' · ') : 'No recorded plays'}
                        </span>
                      </div>
                    );
                  })}
                </div>
              </div>
            ))}
          </div>
          {game.detail_coverage !== 'complete' && <p className="text-xs mt-3" style={{ color: 'var(--text-tertiary)' }}>Some plays weren’t recorded.</p>}
        </section>
      )}

      {game.status === 'completed' && Object.keys(playerStats).length === 0 && aggregateStatsCard}
      {game.status === 'completed' && Object.keys(playerStats).length === 0 && game.detail_coverage !== 'complete' && !hasRecordedStats && (
        <p className="text-xs mt-3 text-center" style={{ color: 'var(--text-tertiary)' }}>Some plays were not recorded.</p>
      )}

      {recovery && (
        <section className="jk-card p-4 mt-3" aria-label="Unsaved referee intent">
          <p className="jk-label">// NOT SAVED</p>
          <p className="font-semibold mt-2 capitalize">{intentLabel}</p>
          {recovery.type === 'stale' ? <>
            <p className="text-sm mt-2">Another referee updated the game. It now shows {game.score.join('–')}. {recovery.change ? `${playerLabel(recovery.change.thrower_id)} · ${resultLabel(recovery.change)} was added.` : ''}</p>
            <Button className="w-full min-h-12 mt-3" onClick={() => executeCommand({ ...recovery.command, client_command_id: commandId(), expected_version: game.version })}>Save my result now</Button>
          </> : <>
            <p className="text-sm mt-2">We could not confirm whether this result saved. Retrying will not create a duplicate.</p>
            <Button className="w-full min-h-12 mt-3" onClick={() => executeCommand(recovery.command)}>Try saving again</Button>
          </>}
          <Button variant="outline" className="w-full min-h-12 mt-2" onClick={() => setRecovery(null)}>Discard unsaved intent</Button>
        </section>
      )}

      {pendingRetoss && (
        <section className="mt-4 p-4 rounded-lg" style={{ background: 'var(--surface-strong)', color: 'var(--text-on-strong)' }}>
          <p className="jk-label" style={{ color: 'var(--accent-gold)' }}>RETOSS</p>
          <h2 className="jk-display text-2xl mt-1">{compactPlayerLabel(pendingRetoss.thrower_id)} throws again</h2>
        </section>
      )}

      {game.status !== 'completed' && (!joined || liveMode === 'referee') && (
        <div role={joined ? 'region' : undefined} aria-label={joined ? 'Referee view' : undefined} className="jk-live-mode-panel">
          <LiveScoringControls
            roster={roster}
            throwOrder={turnHint.throwOrder}
            leftTeamId={left}
            effectiveThrowerId={pendingRetoss?.thrower_id || thrower}
            throwerSelectionLocked={Boolean(pendingRetoss)}
            playerLabel={playerLabel}
            playerProfile={playerProfile}
            joined={joined}
            saving={saving}
            onSelectThrower={setThrower}
            onRecord={record}
            onFifa={() => setActionTarget('fifa')}
            onMoreResults={() => setActionTarget('result')}
          />
        </div>
      )}

      {(game.status === 'completed' || !joined || liveMode === 'referee') && <section className="mt-7" aria-label="Recent plays">
        <p className="jk-label mb-2">// RECENT PLAYS</p>
        <div className="jk-card overflow-hidden">
          {recentPlays.length === 0 && <p className="p-4 text-sm">No results recorded yet.</p>}
          {recentPlays.map((event) => (
            <div key={event.id} className="p-3 flex items-start gap-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
              <PlayerAvatar profile={playerProfile(event.thrower_id)} size={30} linkToProfile={false} />
              <div className="min-w-0 flex-1">
                <span className="font-semibold capitalize">{resultLabel(event)}</span>
                {eventDisposition(event) && <span className="ml-2 text-xs capitalize" style={{ color: 'var(--text-tertiary)' }}>{eventDisposition(event)}</span>}
                <span className="block text-xs mt-0.5 truncate" style={{ color: 'var(--text-secondary)' }}>{compactPlayerLabel(event.thrower_id)}</span>
                {game.status !== 'completed' && event.kind === 'observation' && !correctedEventIds.has(event.id) && (
                  <button type="button" aria-label="Fix this result" className="block mt-1 text-xs underline" onClick={() => openCorrection(event)}>
                    Fix
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>}

      {game.status !== 'completed' && (!joined || liveMode === 'stats') && aggregateStatsCard}

      {game.status !== 'completed' && (!joined || liveMode === 'referee') && <Button className="w-full min-h-12 mt-5" variant={game.status === 'ready_to_finish' ? 'default' : 'ghost'} onClick={() => setActionTarget('game')}>{game.status === 'ready_to_finish' ? 'Finish game' : 'Game options'}</Button>}

      {game.status === 'completed' && !terminalAction && <Button className="w-full min-h-12 mt-5" variant="outline" onClick={() => setTerminalAction('reopen')}>Reopen game</Button>}
      {terminalAction && (
        <section role="dialog" aria-label="Confirm reopen game" className="jk-card p-5 mt-4">
          <h2 className="jk-display text-2xl">Reopen official {game.score.join('–')} game?</h2>
          <p className="text-sm mt-2">Use this only when the final result needs another correction.</p>
          <Button className="w-full min-h-12 mt-4" onClick={() => sendCommand({ kind: 'reopen', target_event_id: terminalEvent?.id, reason: 'mistaken_entry' })}>Confirm reopen</Button>
          <Button variant="outline" className="w-full min-h-12 mt-2" onClick={() => setTerminalAction('')}>Cancel — preserve current game</Button>
        </section>
      )}

      {actionTarget && (
        <LiveGameActionSheet target={actionTarget} game={game} roster={roster} selectedThrowerId={pendingRetoss?.thrower_id || thrower} replayOfEventId={pendingRetoss?.id} playerLabel={playerLabel} playerProfile={playerProfile} saving={saving} onCommand={sendCommand} onCancel={() => setActionTarget(null)} />
      )}
    </main>
  );
}
