import React, { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { diceApi } from '../api.js';
import PlayerAvatar from '../components/PlayerAvatar.jsx';
import PlayerGameStats from '../components/PlayerGameStats.jsx';
import RankedChoice from '../components/RankedChoice.jsx';
import GamePulse from './GamePulse.jsx';
import LiveGameActionSheet from './LiveGameActionSheet.jsx';
import LiveScoringControls from './LiveScoringControls.jsx';
import {
  clearLiveCanonicalVersion,
  clearLiveCommandIntent,
  readLiveCanonicalVersion,
  readLiveCommandIntent,
  writeLiveCanonicalVersion,
  writeLiveCommandIntent,
} from '../liveCommandIntent.js';
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
const LIVE_POLL_INTERVAL_MS = 2000;

function formatLiveDuration(elapsedMs) {
  const elapsed = Math.max(0, Math.floor(elapsedMs / 1000));
  return `${Math.floor(elapsed / 60)}:${String(elapsed % 60).padStart(2, '0')}`;
}

function liveElapsedMs(game, now) {
  const createdAt = Date.parse(game?.created_at);
  if (!Number.isFinite(createdAt)) return 0;
  let activeSince = createdAt;
  let activeTerminalId = null;
  let terminalAt = null;
  const ordered = [...(Array.isArray(game.events) ? game.events : [])]
    .sort((left, right) => Number(left.sequence || 0) - Number(right.sequence || 0));
  ordered.forEach((event, index) => {
    const recordedAt = Date.parse(event.recorded_at);
    if (!Number.isFinite(recordedAt)) return;
    if (!activeTerminalId && ['completion', 'off_roof'].includes(event.kind)) {
      activeTerminalId = event.id;
      terminalAt = recordedAt;
    } else if (activeTerminalId && event.kind === 'correction' && event.target_event_id === activeTerminalId) {
      const replacementTerminal = ordered.slice(index + 1).find((candidate) => (
        candidate.replacement_for === activeTerminalId
        && ['completion', 'off_roof'].includes(candidate.kind)
      ));
      if (replacementTerminal) {
        activeTerminalId = replacementTerminal.id;
        terminalAt = Date.parse(replacementTerminal.recorded_at) || recordedAt;
      } else {
        activeSince = recordedAt;
        activeTerminalId = null;
        terminalAt = null;
      }
    }
  });
  return Math.max(0, (terminalAt || now) - activeSince);
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
      if (command.outcome === 'caught') return command.catcher_id
        ? `${playerLabel(command.catcher_id)} caught ${player}’s table hit · ${score}`
        : `${player} hit the table · no catch · ${score}`;
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
  const userId = auth.user?.id || '';
  const liveCommandStorage = useMemo(() => {
    try { return globalThis.localStorage; } catch { return null; }
  }, []);
  const gameScope = `${userId}:${matchId}`;
  const gameView = useMemo(() => ({ scope: gameScope }), [gameScope]);
  const [game, setGame] = useState(null);
  const [prediction, setPrediction] = useState(null);
  const [pulse, setPulse] = useState(null);
  const [thrower, setThrower] = useState('');
  const [receipt, setReceipt] = useState(null);
  const [error, setError] = useState('');
  const [saving, setSaving] = useState(false);
  const [settingsSaving, setSettingsSaving] = useState(false);
  const [manualRefreshing, setManualRefreshing] = useState(false);
  const [liveMode, setLiveMode] = useState('referee');
  const [actionTarget, setActionTarget] = useState(null);
  const [recovery, setRecovery] = useState(null);
  const [historyRefreshPending, setHistoryRefreshPending] = useState(() => (
    readLiveCanonicalVersion(liveCommandStorage, userId, matchId) > 0
  ));
  const [commandIntent, setCommandIntent] = useState(() => (
    readLiveCommandIntent(liveCommandStorage, userId, matchId)
  ));
  const [terminalAction, setTerminalAction] = useState('');
  const [clock, setClock] = useState(Date.now());
  const latestVersion = useRef(0);
  const latestTurnHistory = useRef('');
  const refreshInFlight = useRef(null);
  const loadGeneration = useRef(0);
  const activeLoads = useRef(new Set());
  const lastForegroundRefresh = useRef(0);
  const commandIntentRef = useRef(commandIntent);
  const commandInFlight = useRef(false);
  const settingsInFlight = useRef(new Set());
  const rankedOverrides = useRef(new Map());
  const pendingCanonicalVersion = useRef(readLiveCanonicalVersion(liveCommandStorage, userId, matchId));
  const activeGameView = useRef(gameView);
  const retryRetainedCommand = useRef(() => {});
  const previousUserId = useRef(userId);

  useLayoutEffect(() => {
    activeGameView.current = gameView;
    return () => {
      if (activeGameView.current === gameView) activeGameView.current = null;
    };
  }, [gameView]);

  const retainCommandIntent = useCallback((intent) => {
    commandIntentRef.current = intent;
    setCommandIntent(intent);
    writeLiveCommandIntent(liveCommandStorage, userId, matchId, intent);
  }, [liveCommandStorage, matchId, userId]);

  const clearCommandIntent = useCallback((scopeUserId = userId) => {
    clearLiveCommandIntent(liveCommandStorage, scopeUserId, matchId);
    commandIntentRef.current = null;
    setCommandIntent(null);
  }, [liveCommandStorage, matchId, userId]);

  useEffect(() => {
    const previous = previousUserId.current;
    if (previous && previous !== userId) clearLiveCommandIntent(liveCommandStorage, previous, matchId);
    previousUserId.current = userId;

    const stored = readLiveCommandIntent(liveCommandStorage, userId, matchId);
    commandIntentRef.current = stored;
    setCommandIntent(stored);
    setRecovery(stored ? {
      type: stored.state === 'review' ? 'review' : 'ambiguous',
      command: stored.command,
    } : null);
  }, [liveCommandStorage, matchId, userId]);

  useEffect(() => {
    const pendingVersion = readLiveCanonicalVersion(liveCommandStorage, userId, matchId);
    pendingCanonicalVersion.current = pendingVersion;
    latestVersion.current = 0;
    latestTurnHistory.current = '';
    setHistoryRefreshPending(pendingVersion > 0);
    setGame(null);
    setPrediction(null);
    setPulse(null);
    setReceipt(null);
    setError('');
    setSaving(false);
    setSettingsSaving(settingsInFlight.current.has(gameScope));
    setManualRefreshing(false);
    setActionTarget(null);
    setTerminalAction('');
  }, [gameScope, liveCommandStorage, matchId, userId]);

  useEffect(() => {
    const observeCanonicalRequirement = () => {
      const storedVersion = readLiveCanonicalVersion(liveCommandStorage, userId, matchId);
      if (storedVersion <= pendingCanonicalVersion.current) return;
      pendingCanonicalVersion.current = storedVersion;
      setHistoryRefreshPending(true);
    };
    window.addEventListener('storage', observeCanonicalRequirement);
    return () => window.removeEventListener('storage', observeCanonicalRequirement);
  }, [liveCommandStorage, matchId, userId]);

  const load = useCallback(async (minimumVersion = 0) => {
    if (!auth.token) return false;
    const requestScope = gameScope;
    const requestView = gameView;
    const requestGeneration = ++loadGeneration.current;
    activeLoads.current.add(requestGeneration);
    setError('');
    try {
      const canonical = await diceApi.getLiveGame(auth.token, matchId);
      if (activeGameView.current !== requestView) return false;
      if (canonical.version < minimumVersion || canonical.version < latestVersion.current) return false;
      latestVersion.current = canonical.version;
      const override = rankedOverrides.current.get(requestScope);
      const predatesSetting = override && requestGeneration <= override.ignoreThrough;
      const canonicalView = predatesSetting && canonical.ranked !== override.ranked
        ? { ...canonical, ranked: override.ranked }
        : canonical;
      if (override && !predatesSetting) override.confirmed = true;
      setGame(canonicalView);
      if (pendingCanonicalVersion.current && canonical.version >= pendingCanonicalVersion.current) {
        clearLiveCanonicalVersion(liveCommandStorage, userId, matchId, canonical.version);
        const remainingVersion = readLiveCanonicalVersion(liveCommandStorage, userId, matchId);
        pendingCanonicalVersion.current = remainingVersion;
        setHistoryRefreshPending(remainingVersion > canonical.version);
      }
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
          if (activeGameView.current !== requestView) return false;
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
        } catch {
          if (activeGameView.current === requestView) setPulse(null);
        }
      }
      if (!pulseLoaded && typeof diceApi.getLivePrediction === 'function') {
        try {
          const estimate = await diceApi.getLivePrediction(auth.token, matchId);
          if (activeGameView.current !== requestView) return false;
          setPrediction(estimate?.match_version === canonical.version ? estimate : null);
        } catch {
          if (activeGameView.current === requestView) setPrediction(null);
        }
      }
      return true;
    } catch (requestError) {
      if (activeGameView.current !== requestView) return false;
      if (!pendingCanonicalVersion.current || latestVersion.current === 0) {
        setError(requestError.message || 'Could not load this live game.');
      }
      return false;
    } finally {
      activeLoads.current.delete(requestGeneration);
      const override = rankedOverrides.current.get(requestScope);
      const olderLoadActive = override && [...activeLoads.current].some((generation) => generation <= override.ignoreThrough);
      if (override?.confirmed && !olderLoadActive) rankedOverrides.current.delete(requestScope);
    }
  }, [auth.token, gameScope, gameView, liveCommandStorage, matchId, userId]);

  const manualReload = async () => {
    if (manualRefreshing) return;
    const requestView = gameView;
    setManualRefreshing(true);
    const loaded = await load();
    if (activeGameView.current !== requestView) return;
    setManualRefreshing(false);
    if (loaded) {
      setReceipt({ message: 'Official game refreshed.', undoSequence: null });
    } else {
      setError('Official game could not refresh. Try again.');
    }
  };

  const refreshCanonical = useCallback(() => {
    if (refreshInFlight.current?.scope === gameScope) return refreshInFlight.current.request;
    const request = load();
    const refresh = { scope: gameScope, request };
    refreshInFlight.current = refresh;
    request.finally(() => {
      if (refreshInFlight.current === refresh) refreshInFlight.current = null;
    });
    return request;
  }, [gameScope, load]);

  useEffect(() => { refreshCanonical(); }, [refreshCanonical]);

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
  // canonical projection while visible, and immediately after a phone resumes.
  const gameLifecycle = game?.status;
  useEffect(() => {
    if (!auth.token || !gameLifecycle || gameLifecycle === 'completed') return undefined;
    const timer = window.setInterval(() => {
      if (document.visibilityState !== 'hidden') refreshCanonical();
    }, LIVE_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [auth.token, gameLifecycle, refreshCanonical]);

  useEffect(() => {
    if (!auth.token || !gameLifecycle) return undefined;
    const refreshOnForeground = () => {
      if (document.visibilityState === 'hidden') return;
      const now = Date.now();
      if (now - lastForegroundRefresh.current < 500) return;
      lastForegroundRefresh.current = now;
      refreshCanonical();
      retryRetainedCommand.current();
    };
    window.addEventListener('focus', refreshOnForeground);
    window.addEventListener('online', refreshOnForeground);
    document.addEventListener('visibilitychange', refreshOnForeground);
    return () => {
      window.removeEventListener('focus', refreshOnForeground);
      window.removeEventListener('online', refreshOnForeground);
      document.removeEventListener('visibilitychange', refreshOnForeground);
    };
  }, [auth.token, gameLifecycle, refreshCanonical]);

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
    if (!game || historyRefreshPending || commandInFlight.current === gameScope || settingsInFlight.current.has(gameScope)) return;
    const commandScope = gameScope;
    const commandView = gameView;
    const commandUserId = userId;
    const commandMatchId = matchId;
    const retained = commandIntentRef.current;
    if (retained && retained.command.client_command_id !== command.client_command_id) {
      setError('Review or discard the unsaved result before recording another.');
      return;
    }
    commandInFlight.current = commandScope;
    retainCommandIntent({ state: 'pending', command });
    setRecovery({ type: 'pending', command });
    setSaving(true);
    setError('');
    try {
      const accepted = await diceApi.sendLiveCommand(auth.token, matchId, command);
      clearLiveCommandIntent(liveCommandStorage, commandUserId, commandMatchId);
      writeLiveCanonicalVersion(liveCommandStorage, commandUserId, commandMatchId, accepted.accepted_version);
      if (activeGameView.current !== commandView) {
        if (activeGameView.current?.scope === commandScope) {
          commandIntentRef.current = null;
          setCommandIntent(null);
          setRecovery(null);
          pendingCanonicalVersion.current = Math.max(
            pendingCanonicalVersion.current,
            readLiveCanonicalVersion(liveCommandStorage, commandUserId, commandMatchId),
          );
          setHistoryRefreshPending(true);
        }
        return;
      }
      setReceipt({
        message: receiptMessage(command, accepted, playerLabel, game.events),
        undoSequence: command.kind === 'record_throw' ? accepted.last_sequence : null,
      });
      setRecovery(null);
      clearCommandIntent();
      setGame((current) => ({
        ...current,
        version: accepted.accepted_version,
        score: accepted.projection.score,
        status: accepted.projection.status,
        detail_coverage: accepted.projection.coverage,
        projection: accepted.projection,
      }));
      latestVersion.current = accepted.accepted_version;
      pendingCanonicalVersion.current = accepted.accepted_version;
      setHistoryRefreshPending(true);
      await load(accepted.accepted_version);
      setActionTarget(null);
      setTerminalAction('');
    } catch (requestError) {
      if (activeGameView.current !== commandView) return;
      if (requestError.status === 409 && requestError.detail?.code === 'dice_live.stale_version') {
        try {
          const canonical = await diceApi.getLiveGame(auth.token, matchId);
          if (activeGameView.current !== commandView) return;
          const conflictVersion = Number(requestError.detail?.current_version);
          if (!Number.isInteger(conflictVersion) || canonical.version < conflictVersion || canonical.version <= command.expected_version) {
            throw new Error('Canonical history has not caught up');
          }
          const change = canonical.events.slice(game.events.length).at(-1);
          setGame(canonical);
          retainCommandIntent({ state: 'review', command });
          setRecovery({ type: 'stale', command, change });
          setError('Another referee changed the canonical game. Review it before resubmitting.');
        } catch {
          if (activeGameView.current !== commandView) return;
          retainCommandIntent({ state: 'pending', command });
          setRecovery({ type: 'ambiguous', command });
          setError('The game changed, but the latest state could not load. Try the exact save again.');
        }
      } else if (requestError.status === 409 && requestError.detail?.code === 'dice_live.command_id_conflict') {
        retainCommandIntent({ state: 'review', command });
        setRecovery({ type: 'review', command });
        setError('This save ID was already used for a different result. Review before resubmitting.');
      } else if (!requestError.status) {
        retainCommandIntent({ state: 'pending', command });
        setRecovery({ type: 'ambiguous', command });
        setError('Delivery was unclear. Retry the exact command ID to avoid a duplicate.');
      } else {
        clearCommandIntent();
        setRecovery(null);
        setError(requestError.message || 'The result was not accepted.');
      }
    } finally {
      if (commandInFlight.current === commandScope) commandInFlight.current = null;
      if (activeGameView.current === commandView) setSaving(false);
    }
  };

  retryRetainedCommand.current = () => {
    const retained = commandIntentRef.current;
    if (retained?.state === 'pending' && !historyRefreshPending && commandInFlight.current !== gameScope) executeCommand(retained.command);
  };

  const sendCommand = (fields) => executeCommand({
    client_command_id: commandId(), expected_version: game.version, match_elapsed_ms: 0, ...fields,
  });

  const updateRanked = async (nextRanked) => {
    if (settingsInFlight.current.has(gameScope)) return;
    const settingsScope = gameScope;
    const settingsView = gameView;
    settingsInFlight.current.add(settingsScope);
    setSettingsSaving(true);
    setError('');
    try {
      const updated = await diceApi.updateLiveSettings(auth.token, matchId, nextRanked);
      rankedOverrides.current.set(settingsScope, {
        ranked: updated.ranked, ignoreThrough: loadGeneration.current, confirmed: false,
      });
      if (activeGameView.current?.scope !== settingsScope) return;
      setGame((current) => (current ? { ...current, ranked: updated.ranked } : current));
      if (activeGameView.current !== settingsView) return;
      await load();
      if (activeGameView.current !== settingsView) return;
      setReceipt({
        message: game.status === 'completed'
          ? `${updated.ranked ? 'Ranked' : 'Unranked'} saved · ratings recalculated.`
          : `${updated.ranked ? 'Ranked' : 'Unranked'} saved.`,
        undoSequence: null,
      });
    } catch (requestError) {
      if (activeGameView.current !== settingsView) return;
      setError(requestError.message || 'The ranked setting could not be saved.');
    } finally {
      settingsInFlight.current.delete(settingsScope);
      if (activeGameView.current?.scope === settingsScope) setSettingsSaving(false);
    }
  };

  const record = (outcome) => sendCommand({
    kind: 'record_throw',
    thrower_id: pendingRetoss?.thrower_id || thrower,
    outcome,
    ...(pendingRetoss ? { replay_of: pendingRetoss.id } : {}),
  });

  const openCorrection = (event) => {
    setActionTarget(event);
  };

  const resubmitCommand = () => {
    const command = {
      ...recovery.command,
      client_command_id: commandId(),
      expected_version: game.version,
    };
    clearCommandIntent();
    executeCommand(command);
  };

  const discardCommandIntent = () => {
    clearCommandIntent();
    setRecovery(null);
    setError('');
  };

  const intentLabel = recovery && [recovery.command.kind.replaceAll('_', ' '), recovery.command.outcome, recovery.command.thrower_id && shortId(recovery.command.thrower_id)].filter(Boolean).join(' · ');
  const commandLocked = saving || settingsSaving || Boolean(commandIntent) || historyRefreshPending;
  const terminalEvent = game?.events && [...game.events].reverse().find((event) => ['completion', 'off_roof'].includes(event.kind));
  const correctedEventIds = new Set(game?.events.filter((event) => event.kind === 'correction').map((event) => event.target_event_id));
  const retossedEventIds = new Set(game?.events.filter((event) => event.kind === 'retoss_decision' && !correctedEventIds.has(event.id)).map((event) => event.target_event_id));
  const eventSequence = new Map(game?.events.map((event) => [event.id, event.sequence]) || []);
  const eventsById = new Map(game?.events.map((event) => [event.id, event]) || []);
  const scoreCheckpoint = [...(game?.events || [])].reverse().find((event) => (
    event.kind === 'score_checkpoint' && !correctedEventIds.has(event.id)
  ));
  const logicalSequence = (event) => {
    const visited = new Set();
    let logicalEvent = event;
    while (logicalEvent?.replacement_for && !visited.has(logicalEvent.id)) {
      visited.add(logicalEvent.id);
      logicalEvent = eventsById.get(logicalEvent.replacement_for) || logicalEvent;
    }
    return logicalEvent?.sequence;
  };
  const scoreAnchorFor = (event) => (
    scoreCheckpoint && logicalSequence(event) < scoreCheckpoint.sequence ? scoreCheckpoint : null
  );
  const correctionNeedsScoreCatchup = Boolean(scoreCheckpoint && game?.events.some((event) => (
    event.kind === 'correction'
    && event.sequence > scoreCheckpoint.sequence
    && (logicalSequence(eventsById.get(event.target_event_id)) || Infinity) < scoreCheckpoint.sequence
  )));
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

  if (!game) {
    return (
      <main className="max-w-xl mx-auto px-4 py-12 text-center">
        <p className="jk-label" role={error ? 'alert' : undefined}>{error || 'Loading game…'}</p>
        {error && (
          <Button variant="outline" className="min-h-12 mt-4" disabled={manualRefreshing} onClick={manualReload}>
            {manualRefreshing ? 'Refreshing…' : 'Reload'}
          </Button>
        )}
      </main>
    );
  }

  const [left, right] = game.team_order;
  return (
    <main className="max-w-xl mx-auto px-4 pt-5 pb-32">
      <div className="flex items-center justify-between gap-3 mb-4">
        <Link to="/dice/live" className="text-sm underline">Live games</Link>
        <button type="button" className="jk-label underline" disabled={manualRefreshing} onClick={manualReload}>
          {manualRefreshing ? 'Refreshing…' : 'Reload'}
        </button>
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
        <p className="jk-live-status mt-3 jk-label"><span>{gameStatus}</span> · {formatLiveDuration(liveElapsedMs(game, clock))}</p>
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

      {(game.status === 'completed' || !joined || liveMode === 'stats') && Object.keys(playerStats).length > 0 && (
        <PlayerGameStats
          live={game.status !== 'completed'}
          coverage={game.detail_coverage}
          statsByPlayer={playerStats}
          teams={game.team_order.map((teamId) => ({
            id: teamId,
            label: game.teams[teamId].map(compactPlayerLabel).join(' + '),
            players: game.teams[teamId].map(playerProfile),
          }))}
        />
      )}

      {receipt && (
        <div className="jk-live-receipt-shell" role="status">
          <div className="jk-live-receipt px-4 py-3 rounded-lg text-sm font-semibold">
            <span className="min-w-0 truncate">{receipt.message}</span>
            {receiptUndoTarget && (
              <button
                type="button"
                className="shrink-0"
                disabled={commandLocked}
                onClick={() => sendCommand({ kind: 'undo_last', target_event_id: receiptUndoTarget.id, reason: 'mistaken_entry' })}
              >Undo</button>
            )}
          </div>
        </div>
      )}
      {error && <p role="alert" className="mt-3 p-3 text-sm rounded-md" style={{ color: 'var(--state-danger)', background: 'var(--surface-sunken)' }}>{error}</p>}
      {historyRefreshPending && (
        <section className="jk-card p-4 mt-3" aria-label="Refreshing saved result">
          <p className="jk-label">// RESULT SAVED</p>
          <p className="text-sm mt-2" role="status">Refreshing official history before another action.</p>
          <Button variant="outline" className="w-full min-h-12 mt-3" disabled={manualRefreshing} onClick={manualReload}>Refresh now</Button>
        </section>
      )}

      {game.status === 'completed' && Object.keys(playerStats).length === 0 && aggregateStatsCard}
      {game.status === 'completed' && Object.keys(playerStats).length === 0 && game.detail_coverage !== 'complete' && !hasRecordedStats && (
        <p className="text-xs mt-3 text-center" style={{ color: 'var(--text-tertiary)' }}>Some plays were not recorded.</p>
      )}

      {recovery && (
        <section className="jk-card p-4 mt-3" aria-label="Unsaved referee intent">
          <p className="jk-label">{recovery.type === 'pending' ? '// SAVING' : '// NOT SAVED'}</p>
          <p className="font-semibold mt-2 capitalize">{intentLabel}</p>
          {recovery.type === 'stale' ? <>
            <p className="text-sm mt-2">Another referee updated the game. It now shows {game.score.join('–')}. {recovery.change ? `${playerLabel(recovery.change.thrower_id)} · ${resultLabel(recovery.change)} was added.` : ''}</p>
            <Button className="w-full min-h-12 mt-3" disabled={saving || settingsSaving || historyRefreshPending} onClick={resubmitCommand}>Save my result now</Button>
          </> : recovery.type === 'review' ? <>
            <p className="text-sm mt-2">This save ID conflicts with another result. Check the game before saving this as a new action.</p>
            <Button className="w-full min-h-12 mt-3" disabled={saving || settingsSaving || historyRefreshPending} onClick={resubmitCommand}>Save as a new action</Button>
          </> : recovery.type === 'pending' ? <>
            <p className="text-sm mt-2" role="status">Saving this result. Keep this screen open.</p>
          </> : <>
            <p className="text-sm mt-2">We could not confirm whether this result saved. Retrying will not create a duplicate.</p>
            <Button className="w-full min-h-12 mt-3" disabled={saving || settingsSaving || historyRefreshPending} onClick={() => executeCommand(recovery.command)}>Try saving again</Button>
          </>}
          {recovery.type !== 'pending' && <Button variant="outline" className="w-full min-h-12 mt-2" onClick={discardCommandIntent}>Discard unsaved intent</Button>}
        </section>
      )}

      {pendingRetoss && (
        <section className="mt-4 p-4 rounded-lg" style={{ background: 'var(--surface-strong)', color: 'var(--text-on-strong)' }}>
          <p className="jk-label" style={{ color: 'var(--accent-gold)' }}>RETOSS</p>
          <h2 className="jk-display text-2xl mt-1">{compactPlayerLabel(pendingRetoss.thrower_id)} throws again</h2>
        </section>
      )}

      {joined && game.status !== 'completed' && liveMode === 'referee' && correctionNeedsScoreCatchup && (
        <section className="jk-card p-4 mt-4" aria-label="Score checkpoint notice">
          <p className="jk-label">// SCORE CHECKPOINT</p>
          <p className="text-sm mt-2">An earlier result changed, but the official {scoreCheckpoint.score.join('–')} checkpoint keeps the score fixed. Catch up the score if the official total should change.</p>
          <Button variant="outline" className="w-full min-h-12 mt-3" onClick={() => setActionTarget('fix_score')}>Catch up score</Button>
        </section>
      )}

      {game.status !== 'completed' && (!joined || liveMode === 'referee') && (
        <div role={joined ? 'region' : undefined} aria-label={joined ? 'Referee view' : undefined} className="jk-live-mode-panel">
          <LiveScoringControls
            roster={roster}
            throwOrder={turnHint.throwOrder}
            turnKnown={turnHint.isKnown}
            leftTeamId={left}
            effectiveThrowerId={pendingRetoss?.thrower_id || thrower}
            throwerSelectionLocked={Boolean(pendingRetoss)}
            playerLabel={playerLabel}
            playerProfile={playerProfile}
            joined={joined}
            saving={commandLocked}
            onSelectThrower={setThrower}
            onRecord={record}
            onTableHit={() => setActionTarget('caught')}
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
                {event.outcome === 'caught' && (
                  <span className="block text-xs mt-0.5 truncate" style={{ color: 'var(--text-secondary)' }}>{event.catcher_id ? `Caught by ${compactPlayerLabel(event.catcher_id)}` : 'No catch'}</span>
                )}
                {game.status !== 'completed' && event.kind === 'observation' && !correctedEventIds.has(event.id) && (
                  <button type="button" aria-label="Fix this result" className="block mt-1 text-xs underline" disabled={commandLocked} onClick={() => openCorrection(event)}>
                    Fix
                  </button>
                )}
              </div>
            </div>
          ))}
        </div>
      </section>}

      {game.status !== 'completed' && (!joined || liveMode === 'stats') && aggregateStatsCard}

      {game.status !== 'completed' && (!joined || liveMode === 'referee') && <Button className="w-full min-h-12 mt-5" variant={game.status === 'ready_to_finish' ? 'default' : 'ghost'} disabled={commandLocked} onClick={() => setActionTarget('game')}>{game.status === 'ready_to_finish' ? 'Finish game' : 'Game options'}</Button>}

      {game.status === 'completed' && !terminalAction && <Button className="w-full min-h-12 mt-5" variant="outline" disabled={commandLocked} onClick={() => setTerminalAction('reopen')}>Reopen game</Button>}
      {(game.status === 'completed' || auth.isAdmin || liveMode === 'referee') && (
        <div className="mt-5">
          <RankedChoice ranked={game.ranked === true} onChange={updateRanked} disabled={commandLocked} />
        </div>
      )}
      {terminalAction && (
        <section role="dialog" aria-label="Confirm reopen game" className="jk-card p-5 mt-4">
          <h2 className="jk-display text-2xl">Reopen official {game.score.join('–')} game?</h2>
          <p className="text-sm mt-2">Use this only when the final result needs another correction.</p>
          <Button className="w-full min-h-12 mt-4" disabled={commandLocked} onClick={() => sendCommand({ kind: 'reopen', target_event_id: terminalEvent?.id, reason: 'mistaken_entry' })}>Confirm reopen</Button>
          <Button variant="outline" className="w-full min-h-12 mt-2" onClick={() => setTerminalAction('')}>Cancel — preserve current game</Button>
        </section>
      )}

      {actionTarget && (
        <LiveGameActionSheet target={actionTarget} game={game} roster={roster} selectedThrowerId={pendingRetoss?.thrower_id || thrower} replayOfEventId={pendingRetoss?.id} playerLabel={playerLabel} playerProfile={playerProfile} scoreAnchor={typeof actionTarget === 'object' ? scoreAnchorFor(actionTarget) : null} saving={commandLocked} onCommand={sendCommand} onCancel={() => setActionTarget(null)} />
      )}
    </main>
  );
}
