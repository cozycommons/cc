import React, { useEffect, useMemo, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import PlayerAvatar from '../components/PlayerAvatar.jsx';
import EloDistribution from '../components/EloDistribution.jsx';
import SinkLeadersChart from '../components/SinkLeadersChart.jsx';
import { diceApi } from '../api.js';
import { rankLeaderboard } from '../leaderboard.js';
import { aggregateRecordedStats, metricLeaders } from '../recordedStats.js';
import { usePageviewTracking } from '../../analytics/usePageviewTracking';
import { calculateStreaks } from './Home.jsx';

const LEADERBOARD_LIMIT = 500;
const VIEWS = ['players', 'streaks', 'duos'];

function SectionLabel({ children, to }) {
  return (
    <div className="flex items-center justify-between gap-3 mb-3">
      <p className="jk-label">// {children}</p>
      {to && <Link className="jk-label underline" to={to}>View all →</Link>}
    </div>
  );
}

function AttributionLeader({ label, players, value, detail, color }) {
  if (!players?.length) return null;
  if (players.length > 1) {
    return (
      <div className="jk-attribution-leader" style={{ '--metric-color': color }} aria-label={`${players.length} players tied for ${label.toLowerCase()}`}>
        <div className="flex -space-x-2 shrink-0">
          {players.slice(0, 3).map((player) => <PlayerAvatar key={player.user_id} profile={player} size={38} linkToProfile />)}
        </div>
        <div className="min-w-0 flex-1">
          <p className="jk-label">{label}</p>
          <p className="font-semibold text-sm">{players.length} players tied</p>
          <p className="text-xs truncate" style={{ color: 'var(--text-secondary)' }}>{players.map((player) => player.display_name).join(' · ')}</p>
        </div>
        <strong className="jk-display text-2xl tabular-nums">{value}</strong>
      </div>
    );
  }
  const [player] = players;
  return (
    <Link to={`/dice/profile/${player.user_id}`} className="jk-attribution-leader" style={{ '--metric-color': color }}>
      <PlayerAvatar profile={player} size={38} linkToProfile={false} />
      <div className="min-w-0 flex-1">
        <p className="jk-label">{label}</p>
        <p className="font-semibold text-sm truncate">{player.display_name}</p>
        <p className="text-xs" style={{ color: 'var(--text-secondary)' }}>{detail}</p>
      </div>
      <strong className="jk-display text-2xl tabular-nums">{value}</strong>
    </Link>
  );
}

function PlayerAttributionCard({ player }) {
  const hitWidth = player.throws ? (player.tableHits / player.throws) * 100 : 0;
  const scoring = player.points + player.sinks;
  const chips = [
    [scoring, 'score'],
    [player.catches, 'catch'],
    [player.fifa_goals, 'FIFA goal'],
    [player.fifa_saves, 'FIFA save'],
    [player.fifa_kicks, 'FIFA kick'],
    [player.misses, 'miss'],
  ].filter(([value]) => value > 0);
  return (
    <Link to={`/dice/profile/${player.user_id}`} className="jk-attribution-player">
      <div className="flex items-center gap-3">
        <PlayerAvatar profile={player} size={42} linkToProfile={false} />
        <div className="min-w-0 flex-1">
          <p className="font-semibold truncate">{player.display_name}</p>
          <p className="text-xs tabular-nums" style={{ color: 'var(--text-secondary)' }}>
            {player.throws} throws · {player.gamesRecorded} game{player.gamesRecorded === 1 ? '' : 's'}
          </p>
        </div>
        <div className="text-right shrink-0">
          <p className="jk-display text-2xl tabular-nums">{player.tableHitRate}%</p>
          <p className="jk-label" style={{ fontSize: 8 }}>TABLE RATE</p>
        </div>
      </div>
      <div className="jk-attribution-rate mt-3" aria-label={`${player.tableHitRate}% table rate`}>
        <span style={{ width: `${hitWidth}%` }} />
      </div>
      {chips.length > 0 && (
        <div className="flex flex-wrap gap-1.5 mt-3">
          {chips.map(([value, label]) => <span key={label} className="jk-stat-chip"><strong>{value}</strong> {label}{value === 1 ? '' : 's'}</span>)}
        </div>
      )}
    </Link>
  );
}

function RecordedPlay({ games }) {
  const aggregate = useMemo(() => aggregateRecordedStats(games || []), [games]);
  if (games === null) {
    return <div className="jk-card p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading recorded play…</div>;
  }
  if (!aggregate.recordedGames) {
    return (
      <div>
        <SectionLabel>Recorded play</SectionLabel>
        <div className="jk-card p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>
          No stats yet! Play a game using the Live Game Feature.
        </div>
      </div>
    );
  }
  const rateLeaders = metricLeaders(aggregate.players, 'tableHitRate', { minimumThrows: 5 });
  const scoreLeaders = metricLeaders(aggregate.players.map((player) => ({ ...player, scores: player.scoringThrows })), 'scores');
  const catchLeaders = metricLeaders(aggregate.players, 'catches');
  const fifaLeaders = metricLeaders(aggregate.players, 'fifaActions');

  return (
    <div aria-label="Recorded player attribution">
      <SectionLabel>Recorded play</SectionLabel>
      <div className="jk-recorded-coverage">
        <div><strong>{aggregate.observations}</strong><span>throws</span></div>
        <div><strong>{aggregate.recordedGames}</strong><span>games logged</span></div>
        <div><strong>{aggregate.completeGames}</strong><span>complete</span></div>
      </div>
      <p className="text-xs mt-2" style={{ color: 'var(--text-tertiary)' }}>Missing plays are excluded, not counted as misses.</p>

      <div className="jk-attribution-leaders mt-4">
        <AttributionLeader label="TABLE RATE" players={rateLeaders} value={rateLeaders[0] ? `${rateLeaders[0].tableHitRate}%` : null} detail={rateLeaders[0] ? `${rateLeaders[0].throws} recorded throws` : null} color="var(--team1-color)" />
        <AttributionLeader label="SCORES" players={scoreLeaders} value={scoreLeaders[0]?.scores} detail={scoreLeaders[0] ? `${scoreLeaders[0].points} points · ${scoreLeaders[0].sinks} sinks` : null} color="var(--state-success)" />
        <AttributionLeader label="CATCHES" players={catchLeaders} value={catchLeaders[0]?.catches} detail={catchLeaders[0] ? `${catchLeaders[0].table_catches} table · ${catchLeaders[0].fifa_catches} FIFA` : null} color="var(--team2-color)" />
        <AttributionLeader label="FIFA ACTIONS" players={fifaLeaders} value={fifaLeaders[0]?.fifaActions} detail={fifaLeaders[0] ? `${fifaLeaders[0].fifa_goals} goals · ${fifaLeaders[0].fifa_saves} saves` : null} color="var(--accent-gold)" />
      </div>

      <div className="mt-6">
        <p className="jk-label mb-3">PLAYER BREAKDOWN</p>
        <div className="jk-attribution-grid">
          {aggregate.players.map((player) => <PlayerAttributionCard key={player.user_id} player={player} />)}
        </div>
      </div>
    </div>
  );
}

function PlayerView({ auth, elo, sinks, selfSinks, games }) {
  const ranked = useMemo(
    () => rankLeaderboard(elo || [], 'elo_rating', { provisionalKey: 'is_provisional' }),
    [elo],
  );
  const leaders = ranked.filter((profile) => !profile.is_provisional && profile.rank === 1);
  const leader = leaders[0];
  const currentUserId = auth?.profile?.user_id || auth?.user?.id;

  if (elo === null || sinks === null || selfSinks === null) {
    return <div className="jk-card p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading player stats…</div>;
  }

  return (
    <section className="jk-stats-panel space-y-7" aria-label="Player stats">
      {leaders.length > 1 ? (
        <div className="jk-stats-tie-card is-players" aria-label={`${leaders.length} players tied for first`}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="jk-label">#1 TIE</p>
              <h2 className="jk-display text-2xl">{leaders.length} players tied</h2>
            </div>
            <div className="text-right shrink-0">
              <p className="jk-display text-3xl tabular-nums">{leader.elo_rating}</p>
              <p className="jk-label">ELO</p>
            </div>
          </div>
          <div className="jk-stats-tie-list">
            {leaders.map((profile) => (
              <Link key={profile.user_id} to={`/dice/profile/${profile.user_id}`} className="jk-stats-tie-entry">
                <PlayerAvatar profile={profile} size={38} linkToProfile={false} />
                <span className="font-semibold truncate">{profile.display_name}</span>
              </Link>
            ))}
          </div>
        </div>
      ) : leader ? (
        <Link to={`/dice/profile/${leader.user_id}`} className="jk-stats-hero is-players">
          <div className="flex items-center gap-3 min-w-0">
            <PlayerAvatar profile={leader} size={58} linkToProfile={false} />
            <div className="min-w-0">
              <p className="jk-label">#1 PLAYER</p>
              <h2 className="jk-display text-3xl truncate">{leader.display_name}</h2>
            </div>
          </div>
          <div className="text-right shrink-0">
            <p className="jk-display text-4xl tabular-nums">{leader.elo_rating}</p>
            <p className="jk-label">ELO</p>
          </div>
        </Link>
      ) : (
        <div className="jk-card p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>No ranked players yet.</div>
      )}

      <div>
        <SectionLabel to="/dice/leaderboard/elo">Rating distribution</SectionLabel>
        <EloDistribution entries={elo} currentUserId={currentUserId} />
      </div>

      <div>
        <SectionLabel>Scoring</SectionLabel>
        <SinkLeadersChart sinks={sinks} selfSinks={selfSinks} currentUserId={currentUserId} />
      </div>

      <RecordedPlay games={games} />
    </section>
  );
}

function StreakBars({ records }) {
  const best = rankLeaderboard([...records]
    .filter((record) => record.best > 0)
    .sort((left, right) => right.best - left.best || left.display_name.localeCompare(right.display_name)), 'best')
    .filter((record) => record.rank <= 5);
  const maximum = best[0]?.best || 1;

  return (
    <div className="jk-card jk-streak-chart" aria-label="Longest win streaks" style={{ gridTemplateColumns: `repeat(${best.length}, minmax(0, 1fr))` }}>
      {best.map((record) => (
        <Link
          key={record.user_id}
          to={`/dice/stats/streaks/${encodeURIComponent(record.user_id)}`}
          className="jk-streak-column"
          aria-label={`${record.display_name}, ${record.best} wins, rank ${record.rank}`}
        >
          <span className="jk-display text-xl tabular-nums">{record.best}</span>
          <span className="jk-streak-bar-space" aria-hidden="true">
            <span className="jk-streak-bar" style={{ height: `${Math.max(12, (record.best / maximum) * 100)}%` }} />
          </span>
          <PlayerAvatar profile={record} size={34} linkToProfile={false} />
          <span className="jk-streak-name">{record.display_name.split(' ')[0]}</span>
        </Link>
      ))}
    </div>
  );
}

function StreakView({ games }) {
  const records = useMemo(() => calculateStreaks(games || []), [games]);
  const active = records
    .filter((record) => record.current > 1)
    .sort((left, right) => right.current - left.current || right.best - left.best);
  const hottest = active[0];
  const leaders = hottest ? active.filter((record) => record.current === hottest.current) : [];
  const alsoActive = active.slice(leaders.length);

  if (games === null) {
    return <div className="jk-card p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading streaks…</div>;
  }
  if (!records.length) {
    return <div className="jk-card p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>No multi-game streaks yet.</div>;
  }

  return (
    <section className="jk-stats-panel space-y-7" aria-label="Win streaks">
      {leaders.length > 1 ? (
        <div className="jk-stats-tie-card is-streaks" aria-label={`${leaders.length} players tied for the longest active streak`}>
          <div className="flex items-start justify-between gap-3">
            <div>
              <p className="jk-label">ACTIVE LEADERS</p>
              <h2 className="jk-display text-2xl">{leaders.length} players tied</h2>
            </div>
            <div className="text-right shrink-0">
              <p className="jk-display text-4xl tabular-nums">{hottest.current}</p>
              <p className="jk-label">STRAIGHT</p>
            </div>
          </div>
          <div className="jk-stats-tie-list">
            {leaders.map((record) => (
              <Link key={record.user_id} to={`/dice/stats/streaks/${encodeURIComponent(record.user_id)}`} className="jk-stats-tie-entry">
                <PlayerAvatar profile={record} size={38} linkToProfile={false} />
                <span className="font-semibold truncate">{record.display_name}</span>
              </Link>
            ))}
          </div>
        </div>
      ) : hottest ? (
        <Link to={`/dice/stats/streaks/${encodeURIComponent(hottest.user_id)}`} className="jk-stats-hero is-streaks">
          <div className="flex items-center gap-3 min-w-0">
            <PlayerAvatar profile={hottest} size={58} linkToProfile={false} />
            <div className="min-w-0">
              <p className="jk-label">ACTIVE RUN</p>
              <h2 className="jk-display text-3xl truncate">{hottest.display_name}</h2>
            </div>
          </div>
          <div className="text-right shrink-0">
            <p className="jk-display text-5xl tabular-nums">{hottest.current}</p>
            <p className="jk-label">STRAIGHT</p>
          </div>
        </Link>
      ) : (
        <div className="jk-streak-idle">
          <span aria-hidden="true">○</span>
          <p>No active win streak.</p>
        </div>
      )}

      {alsoActive.length > 0 && (
        <div>
          <SectionLabel>Also active</SectionLabel>
          <div className="jk-streak-chip-grid">
            {alsoActive.map((record) => (
              <Link key={record.user_id} to={`/dice/stats/streaks/${encodeURIComponent(record.user_id)}`} className="jk-streak-chip">
                <PlayerAvatar profile={record} size={30} linkToProfile={false} />
                <span className="truncate">{record.display_name}</span>
                <strong>{record.current}W</strong>
              </Link>
            ))}
          </div>
        </div>
      )}

      <div>
        <SectionLabel>Longest runs</SectionLabel>
        <StreakBars records={records} />
      </div>
    </section>
  );
}

function DuoRow({ duo, rank }) {
  return (
    <Link to={`/dice/stats/duos/${encodeURIComponent(duo.duo_id)}`} className="jk-row flex items-center gap-3 px-3 py-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
      <span className="jk-label w-5 text-center">{duo.rank || rank}</span>
      <div className="flex -space-x-2 shrink-0">{duo.members.map((member) => <PlayerAvatar key={member.user_id} profile={member} size={34} linkToProfile={false} />)}</div>
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-sm truncate">{duo.members.map((member) => member.display_name).join(' + ')}</p>
        <p className="jk-label mt-1" style={{ fontSize: 10 }}>{duo.wins}–{duo.losses} · {duo.games} games</p>
      </div>
      <p className="jk-display text-xl tabular-nums shrink-0">{duo.elo}</p>
    </Link>
  );
}

function ProvisionalDuo({ duo }) {
  return (
    <Link to={`/dice/stats/duos/${encodeURIComponent(duo.duo_id)}`} className="jk-provisional-duo">
      <div className="flex -space-x-2 shrink-0">{duo.members.map((member) => <PlayerAvatar key={member.user_id} profile={member} size={32} linkToProfile={false} />)}</div>
      <div className="min-w-0 flex-1">
        <p className="font-semibold text-sm truncate">{duo.members.map((member) => member.display_name).join(' + ')}</p>
        <p className="jk-label" style={{ fontSize: 9 }}>{duo.games} of 3 games</p>
      </div>
      <div className="text-right shrink-0">
        <p className="jk-display text-lg tabular-nums">{duo.elo}</p>
        <p className="jk-label" style={{ fontSize: 8 }}>PROVISIONAL</p>
      </div>
    </Link>
  );
}

function DuoView({ auth }) {
  const [ladder, setLadder] = useState(null);
  const [error, setError] = useState(false);
  const registered = Boolean(auth?.token && auth?.profile);

  useEffect(() => {
    if (!registered) return;
    if (typeof diceApi.getDuoLadder !== 'function') {
      setLadder({ ranked: [], to_watch: [] });
      return;
    }
    setError(false);
    diceApi.getDuoLadder(auth.token).then(setLadder).catch(() => setError(true));
  }, [auth?.token, registered]);

  if (!registered) return <div className="jk-card p-4 text-sm">Sign in with a registered Dice profile to view duo ratings.</div>;
  if (error) return <div className="jk-card p-4 text-sm">Could not load duo ratings.</div>;
  if (!ladder) return <div className="jk-card p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading duos…</div>;

  const leaders = ladder.ranked.filter((duo, index) => (duo.rank ?? index + 1) === 1);
  const leader = leaders[0];
  const ranked = ladder.ranked.slice(leaders.length);
  return (
    <section className="jk-stats-panel space-y-7" aria-label="Duo stats">
      {leaders.length > 1 ? (
        <div className="jk-stats-tie-card is-duos" aria-label={`${leaders.length} duos tied for first`}>
          <div>
            <p className="jk-label">#1 TIE</p>
            <h2 className="jk-display text-2xl">{leaders.length} duos tied</h2>
          </div>
          <div className="jk-stats-tie-list">
            {leaders.map((duo) => (
              <Link key={duo.duo_id} to={`/dice/stats/duos/${encodeURIComponent(duo.duo_id)}`} className="jk-stats-tie-entry">
                <div className="flex -space-x-2 shrink-0">{duo.members.map((member) => <PlayerAvatar key={member.user_id} profile={member} size={34} linkToProfile={false} />)}</div>
                <span className="font-semibold text-sm truncate flex-1">{duo.members.map((member) => member.display_name).join(' + ')}</span>
                <span className="jk-display text-lg tabular-nums">{duo.elo}</span>
              </Link>
            ))}
          </div>
          <p className="jk-label">Equal ELO means an equal rank.</p>
        </div>
      ) : leader ? (
        <Link to={`/dice/stats/duos/${encodeURIComponent(leader.duo_id)}`} className="jk-stats-hero is-duos">
          <div className="flex items-center gap-3 min-w-0">
            <div className="flex -space-x-3 shrink-0">{leader.members.map((member) => <PlayerAvatar key={member.user_id} profile={member} size={54} linkToProfile={false} />)}</div>
            <div className="min-w-0">
              <p className="jk-label">#1 DUO</p>
              <h2 className="jk-display text-2xl truncate">{leader.members.map((member) => member.display_name).join(' + ')}</h2>
              <p className="text-sm">{leader.wins}–{leader.losses} · {Math.round(leader.win_rate * 100)}%</p>
              <p className="jk-label mt-1" style={{ fontSize: 8 }}>RANKED BY ELO</p>
            </div>
          </div>
          <div className="text-right shrink-0">
            <p className="jk-display text-4xl tabular-nums">{leader.elo}</p>
            <p className="jk-label">ELO</p>
          </div>
        </Link>
      ) : (
        <div className="jk-card p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>No duo has completed three ranked games yet.</div>
      )}

      {ranked.length > 0 && (
        <div>
          <SectionLabel>Ranked duos</SectionLabel>
          <p className="text-xs -mt-1 mb-3" style={{ color: 'var(--text-tertiary)' }}>Highest ELO ranks first.</p>
          <div className="jk-card overflow-hidden">{ranked.map((duo, index) => <DuoRow key={duo.duo_id} duo={duo} rank={duo.rank ?? leaders.length + index + 1} />)}</div>
        </div>
      )}

      <div>
        <SectionLabel to="/dice/elo-explained">Provisional duos</SectionLabel>
        {ladder.to_watch.length > 0 ? (
          <div className="jk-provisional-grid">{ladder.to_watch.map((duo) => <ProvisionalDuo key={duo.duo_id} duo={duo} />)}</div>
        ) : (
          <div className="jk-card p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>No provisional duos right now.</div>
        )}
      </div>
    </section>
  );
}

export default function Stats({ auth }) {
  const [games, setGames] = useState(null);
  const [elo, setElo] = useState(null);
  const [sinks, setSinks] = useState(null);
  const [selfSinks, setSelfSinks] = useState(null);
  const [params, setParams] = useSearchParams();
  const requestedView = params.get('view');
  const view = VIEWS.includes(requestedView) ? requestedView : 'players';

  usePageviewTracking('dice', 'stats', '/dice/stats');
  useEffect(() => {
    (typeof diceApi.getAllGames === 'function' ? diceApi.getAllGames() : diceApi.getGames(200)).then(setGames).catch(() => setGames([]));
    diceApi.getEloLeaderboard(LEADERBOARD_LIMIT, true).then(setElo).catch(() => setElo([]));
    diceApi.getSinkLeaderboard(LEADERBOARD_LIMIT, false).then(setSinks).catch(() => setSinks([]));
    diceApi.getSelfSinkLeaderboard(LEADERBOARD_LIMIT, false).then(setSelfSinks).catch(() => setSelfSinks([]));
  }, []);

  const choose = (next) => setParams(next === 'players' ? {} : { view: next });
  return (
    <main className="max-w-2xl mx-auto px-4 sm:px-6 py-8">
      <div className="mb-5">
        <p className="jk-label">// DICE STATS</p>
        <h1 className="jk-display text-4xl mt-1">Stats</h1>
      </div>
      <div className="jk-stats-tabs mb-7" role="tablist" aria-label="Dice stats views">
        {VIEWS.map((tab) => (
          <button key={tab} type="button" role="tab" data-view={tab} aria-selected={view === tab} onClick={() => choose(tab)}>
            {tab}
          </button>
        ))}
      </div>
      {view === 'players' && <PlayerView auth={auth} elo={elo} sinks={sinks} selfSinks={selfSinks} games={games} />}
      {view === 'streaks' && <StreakView games={games} />}
      {view === 'duos' && <DuoView auth={auth} />}
    </main>
  );
}

export { DuoRow, PlayerView, RecordedPlay, StreakBars, StreakView };
