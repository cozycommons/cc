const activeObservations = (events = []) => {
  const corrections = new Map();
  const replacements = new Map();
  const retossed = new Set();

  for (const event of events) {
    if (event.kind === 'correction') corrections.set(event.target_event_id, event);
    if (event.replacement_for) replacements.set(event.replacement_for, event);
    if (event.kind === 'retoss_decision' && event.target_event_id) retossed.add(event.target_event_id);
  }

  const effective = (event) => {
    if (retossed.has(event.id)) return null;
    if (!corrections.has(event.id)) return event;
    const replacement = replacements.get(event.id);
    return replacement ? effective(replacement) : null;
  };

  return events
    .filter((event) => event.kind === 'observation' && !event.replacement_for)
    .map((event) => ({ rootId: event.id, event: effective(event) }))
    .filter(({ event }) => event?.kind === 'observation');
};

/**
 * Suggest the next physical throw without persisting a separate lineup model.
 * Teams take loose two-throw turns; within a team, the teammate who did not
 * throw most recently goes next. Recorded history therefore makes a manual
 * first-throw swap naturally sticky on the following round.
 */
export const deriveLiveTurn = (game) => {
  const teamOrder = game?.team_order || [];
  const teams = game?.teams || {};
  const observations = activeObservations(game?.events);
  const fallback = teams[teamOrder[0]]?.[0] || '';

  if (!observations.length) {
    return {
      nextThrowerId: fallback,
      throwOrder: teamOrder.flatMap((teamId) => teams[teamId] || []),
      historyKey: 'empty',
    };
  }

  const eventTeam = (event) => event.throwing_team_id || teamOrder.find(
    (teamId) => teams[teamId]?.includes(event.thrower_id),
  );
  const last = observations.at(-1);
  const previous = observations.at(-2);
  const lastTeam = eventTeam(last.event);
  const targetTeam = (previous && eventTeam(previous.event)) === lastTeam
    ? teamOrder.find((teamId) => teamId !== lastTeam)
    : lastTeam;
  const nextPlayersFor = (teamId) => {
    const players = teams[teamId] || [];
    const lastForTeam = [...observations]
      .reverse()
      .find(({ event }) => eventTeam(event) === teamId);
    const next = players.find((playerId) => playerId !== lastForTeam?.event.thrower_id)
      || players[0];
    return next ? [next, ...players.filter((playerId) => playerId !== next)] : [];
  };
  const upcomingTeams = [targetTeam, ...teamOrder.filter((teamId) => teamId !== targetTeam)];
  const throwOrder = upcomingTeams.flatMap(nextPlayersFor);
  const nextThrowerId = throwOrder[0] || fallback;

  return {
    nextThrowerId,
    throwOrder,
    historyKey: observations.map(({ rootId, event }) => `${rootId}:${event.id}`).join('|'),
  };
};
