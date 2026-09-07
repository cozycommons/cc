import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { diceApi } from '../api.js';
import GameRow from '../components/GameRow.jsx';
import LeaderboardRow from '../components/LeaderboardRow.jsx';
import TournamentRow from '../components/TournamentRow.jsx';
import PhotoGallery from '../components/PhotoGallery.jsx';
import PlayerAvatar from '../components/PlayerAvatar.jsx';
import SinkLeadersChart from '../components/SinkLeadersChart.jsx';
import { leaderboardPreview, rankLeaderboard } from '../leaderboard.js';
import { usePageviewTracking } from '../../analytics/usePageviewTracking';
import LegacyHome from './LegacyHome.jsx';

function SectionHeader({ label, viewAllTo }) {
  return (
    <div className="flex items-center justify-between mb-3">
      <p className="jk-label">{label}</p>
      {viewAllTo && (
        <Link to={viewAllTo} style={{ fontFamily: 'var(--font-mono)', fontSize: 12, color: 'var(--text-secondary)' }}>
          View all →
        </Link>
      )}
    </div>
  );
}

// Most dashboard previews show five rows before linking to their full page.
const PREVIEW_LIMIT = 5;
const LEADERBOARD_LIMIT = 500;
const HOME_MATCH_LIMIT = 3;
function hasMore(list) {
  return Array.isArray(list) && list.length >= PREVIEW_LIMIT;
}

function splitTournaments(tournaments, now = Date.now()) {
  const valid = (tournaments || []).filter((tournament) => Number.isFinite(Date.parse(tournament.starts_at)));
  return {
    upcoming: valid
      .filter((tournament) => Date.parse(tournament.starts_at) >= now)
      .sort((left, right) => Date.parse(left.starts_at) - Date.parse(right.starts_at)),
    past: valid
      .filter((tournament) => Date.parse(tournament.starts_at) < now)
      .sort((left, right) => Date.parse(right.starts_at) - Date.parse(left.starts_at)),
  };
}

function matchStory(game) {
  const players = game.players || [];
  const selfSinks = players.reduce((total, player) => total + (player.self_sinks || 0), 0);
  if (selfSinks > 0) return `${selfSinks} self-sink${selfSinks === 1 ? '' : 's'}`;

  if (game.ranked) {
    const biggestGain = players
      .map((player) => ({ ...player, change: (player.elo_after ?? 0) - (player.elo_before ?? 0) }))
      .filter((player) => player.elo_before != null && player.elo_after != null && player.change > 0)
      .sort((left, right) => right.change - left.change)[0];
    if (biggestGain) return `${biggestGain.display_name} +${biggestGain.change} ELO`;
  }

  const margin = Math.abs(game.team1_score - game.team2_score);
  if (margin <= 2) return 'Down to the wire';
  if (margin >= 8) return 'Statement win';
  return null;
}

function calculateStreaks(games) {
  const byPlayer = new Map();
  [...(games || [])].sort((left, right) => new Date(left.played_at) - new Date(right.played_at)).forEach((game) => {
    (game.players || []).forEach((player) => {
      const record = byPlayer.get(player.user_id) || { user_id: player.user_id, display_name: player.display_name, current: 0, best: 0, latest: null };
      const won = game.winner_team === player.team;
      record.latest = won;
      if (won) {
        record.current += 1;
        record.best = Math.max(record.best, record.current);
      } else {
        record.current = 0;
      }
      byPlayer.set(player.user_id, record);
    });
  });
  return [...byPlayer.values()]
    .map((record) => ({ ...record, current: record.latest ? record.current : 0 }))
    .filter((record) => record.current > 1 || record.best > 1)
    .sort((left, right) => right.current - left.current || right.best - left.best);
}

function calculateSynergies(games) {
  const pairs = new Map();
  (games || []).forEach((game) => {
    const teams = [1, 2].map((team) => (game.players || []).filter((player) => player.team === team));
    teams.forEach((players) => {
      for (let index = 0; index < players.length; index += 1) {
        for (let other = index + 1; other < players.length; other += 1) {
          const pair = [players[index], players[other]].sort((left, right) => left.user_id.localeCompare(right.user_id));
          const key = pair.map((player) => player.user_id).join(':');
          const record = pairs.get(key) || { user_id: key, players: pair.map((player) => player.display_name), wins: 0, losses: 0 };
          if (game.winner_team === pair[0].team) record.wins += 1;
          else record.losses += 1;
          pairs.set(key, record);
        }
      }
    });
  });
  return [...pairs.values()]
    .filter((record) => record.wins + record.losses >= 2)
    .sort((left, right) => right.wins - left.wins || left.losses - right.losses);
}

function livePlayerLabel(game, playerId) {
  return game.player_names?.[playerId] || String(playerId || '').split('-')[0];
}

function livePlayerProfile(game, playerId) {
  return { user_id: playerId, display_name: livePlayerLabel(game, playerId), avatar_url: game.player_avatars?.[playerId], ...game.player_stats?.[playerId] };
}

function liveProbability(game, left, right, prediction) {
  if (prediction?.status === 'available' && prediction.match_version === game.version) {
    return { left: prediction.team1_win_probability, right: prediction.team2_win_probability, source: prediction.pregame_source };
  }
  const average = (team) => {
    const ratings = game.teams[team].map((id) => game.player_stats?.[id]?.elo_rating).filter(Number.isFinite);
    return ratings.length ? ratings.reduce((sum, rating) => sum + rating, 0) / ratings.length : 1500;
  };
  const leftRating = average(left);
  const rightRating = average(right);
  const leftProbability = 1 / (1 + (10 ** ((rightRating - leftRating) / 400)));
  return { left: leftProbability, right: 1 - leftProbability, source: 'elo_prior' };
}

function formatLiveDuration(createdAt, now) {
  const started = Date.parse(createdAt);
  if (!Number.isFinite(started)) return '0:00';
  const elapsed = Math.max(0, Math.floor((now - started) / 1000));
  const minutes = Math.floor(elapsed / 60);
  const seconds = String(elapsed % 60).padStart(2, '0');
  return `${minutes}:${seconds}`;
}

function LiveGameRow({ game, userId, prediction }) {
  const [now, setNow] = useState(Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  const [left, right] = game.team_order;
  const joined = game.referees?.some((referee) => referee.user_id === userId && !referee.left_at);
  const teamLabel = (team) => game.teams[team].map((playerId) => livePlayerLabel(game, playerId)).join(' + ');
  const teamStats = (team) => {
    const profiles = game.teams[team].map((playerId) => game.player_stats?.[playerId]).filter(Boolean);
    const ratings = profiles.map((profile) => profile.elo_rating).filter(Number.isFinite);
    const parts = [];
    if (ratings.length) parts.push(`${Math.round(ratings.reduce((total, rating) => total + rating, 0) / ratings.length)} ELO`);
    if (profiles.length) parts.push(`${profiles.reduce((total, profile) => total + (profile.sinks || 0), 0)} sinks`);
    return parts.join(' · ') || 'Stats pending';
  };
  const leftStats = teamStats(left);
  const rightStats = teamStats(right);
  const probability = liveProbability(game, left, right, prediction);

  return (
    <Link
      to={`/dice/live/${game.id}`}
      className="jk-row block px-4 py-4"
      style={{ borderBottom: '1px solid var(--border-subtle)' }}
    >
      <div className="flex items-center justify-between gap-3 mb-2">
        <span className="jk-label" style={{ color: 'var(--state-danger)', fontSize: 10 }}>● Live · {formatLiveDuration(game.created_at, now)}</span>
        <span className="jk-label" style={{ fontSize: 10 }}>{joined ? 'Refereeing' : 'Open game'}</span>
      </div>
      <div className="grid grid-cols-[minmax(0,1fr)_auto_minmax(0,1fr)] items-center gap-3">
        <div className="flex items-center gap-1.5 min-w-0">
          <div className="flex -space-x-2 shrink-0">{game.teams[left].map((playerId) => <PlayerAvatar key={playerId} profile={livePlayerProfile(game, playerId)} size={28} linkToProfile={false} />)}</div>
          <div className="min-w-0"><p className="font-semibold text-sm min-w-0 break-words">{teamLabel(left)}</p><p className="jk-label mt-0.5" style={{ fontSize: 9 }}>{leftStats}</p></div>
        </div>
        <p className="jk-display text-4xl tabular-nums">{game.score[0]}–{game.score[1]}</p>
        <div className="flex items-center justify-end gap-1.5 min-w-0">
          <div className="min-w-0"><p className="font-semibold text-sm text-right min-w-0 break-words">{teamLabel(right)}</p><p className="jk-label mt-0.5 text-right" style={{ fontSize: 9 }}>{rightStats}</p></div>
          <div className="flex -space-x-2 shrink-0">{game.teams[right].map((playerId) => <PlayerAvatar key={playerId} profile={livePlayerProfile(game, playerId)} size={28} linkToProfile={false} />)}</div>
        </div>
      </div>
      <div className="mt-3" aria-label={`Live probability ${Math.round(probability.left * 100)} percent to ${Math.round(probability.right * 100)} percent`}>
        <div className="flex justify-between jk-label" style={{ fontSize: 9 }}><span>{Math.round(probability.left * 100)}%</span><span>{Math.round(probability.right * 100)}%</span></div>
        <div className="jk-live-odds-track mt-1"><div className="jk-live-odds-left" style={{ width: `${Math.round(probability.left * 100)}%` }} /><div className="jk-live-odds-right" /></div>
        <p className="jk-label mt-1" style={{ fontSize: 8 }}>{probability.source === 'elo_snapshot' ? 'Live probability · ELO snapshot' : 'Live probability · ELO prior'}</p>
      </div>
    </Link>
  );
}

function LiveHomeSection({ auth, games, predictions }) {
  return (
    <section className="mb-10" aria-labelledby="live-home-heading">
      <div id="live-home-heading">
        <SectionHeader label="// LIVE GAMES" viewAllTo="/dice/live" />
      </div>
      <div className="jk-card overflow-hidden">
        {games?.map((game) => <LiveGameRow key={game.id} game={game} userId={auth.user?.id} prediction={predictions?.[game.id]} />)}
      </div>
    </section>
  );
}

function EloSection({ entries, currentUserId }) {
  const ranked = rankLeaderboard(entries, 'elo_rating', { provisionalKey: 'is_provisional' });
  const preview = leaderboardPreview(ranked, currentUserId);
  const eloRange = Math.max(1, ...ranked.filter((profile) => !profile.is_provisional).map((profile) => Math.abs(profile.elo_rating - 1500)));
  return (
    <section className="mb-10">
      <SectionHeader label="// ELO STANDINGS" viewAllTo="/dice/leaderboard/elo" />
      <div className="jk-card overflow-hidden">
        {entries === null && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading…</p>}
        {entries?.length === 0 && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>No standings yet.</p>}
        {preview.leaders.map((profile) => (
          <LeaderboardRow key={profile.user_id} rank={profile.rank} profile={profile} value={profile.elo_rating} valueLabel="ELO" barMode="elo" maxValue={eloRange} unranked={profile.is_provisional} isCurrentUser={profile.user_id === currentUserId} />
        ))}
        {preview.current && <LeaderboardRow rank={preview.current.rank} profile={preview.current} value={preview.current.elo_rating} valueLabel="ELO" barMode="elo" maxValue={eloRange} unranked={preview.current.is_provisional} isCurrentUser />}
      </div>
      <Link to="/dice/elo-explained" style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-tertiary)' }} className="inline-block mt-2">
        How does ELO work? →
      </Link>
    </section>
  );
}

function SinkLeadersSection({ sinks, selfSinks, currentUserId }) {
  return (
    <section className="mb-10">
      <SectionHeader label="// SINK LEADERS" />
      <SinkLeadersChart sinks={sinks} selfSinks={selfSinks} currentUserId={currentUserId} />
    </section>
  );
}

function CurrentStreaksSection({ games, limit = 3, viewAllTo = '/dice/stats' }) {
  const streaks = calculateStreaks(games);
  const current = streaks.filter((record) => record.current > 1).slice(0, limit);
  if (current.length === 0) return null;

  return (
    <section className="mb-10">
      <SectionHeader label="// CURRENT WIN STREAKS" viewAllTo={viewAllTo} />
      <div className="jk-card overflow-hidden">
        {current.map((record) => (
          <div key={record.user_id} className="flex items-center justify-between gap-2 px-4 py-2.5" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
            <span className="truncate text-sm font-medium">{record.display_name}</span>
            <span className="text-sm" style={{ color: 'var(--text-secondary)' }}>{record.current} wins</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function HistoricalRecordsSection({ games }) {
  const streaks = calculateStreaks(games);
  const synergies = calculateSynergies(games);
  if (streaks.length === 0 && synergies.length === 0) return null;
  const best = [...streaks].sort((left, right) => right.best - left.best || right.current - left.current).slice(0, 3);

  return (
    <section className="mb-10">
      <SectionHeader label="// RECORDS" />
      <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
        <div className="jk-card overflow-hidden">
          <p className="jk-label px-3 pt-3" style={{ fontSize: 10 }}>BEST RUNS</p>
          {best.map((record) => (
            <div key={record.user_id} className="flex items-center justify-between gap-2 px-3 py-2" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
              <span className="truncate text-sm font-medium">{record.display_name}</span>
              <span className="jk-display text-lg tabular-nums">{record.best}W</span>
            </div>
          ))}
        </div>
        <div className="jk-card overflow-hidden">
          <p className="jk-label px-3 pt-3" style={{ fontSize: 10 }}>TOP SYNERGY</p>
          {synergies.slice(0, 3).map((record) => (
            <div key={record.user_id} className="px-3 py-2" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
              <p className="truncate text-sm font-medium">{record.players.join(' + ')}</p>
              <p className="jk-label mt-1" style={{ fontSize: 10 }}>{record.wins}–{record.losses} together</p>
            </div>
          ))}
          {synergies.length === 0 && <p className="p-3 text-xs" style={{ color: 'var(--text-tertiary)' }}>No repeat pairings yet.</p>}
        </div>
      </div>
    </section>
  );
}

function TournamentHighlights({ tournaments }) {
  const { upcoming, past } = splitTournaments(tournaments);
  const nextTournament = upcoming[0];
  const recentTournament = past[0];
  const champions = recentTournament?.bracket?.champion || [];
  const playedBracketGames = recentTournament ? ['semi1', 'semi2', 'final']
    .map((round) => recentTournament.bracket?.[round]?.game)
    .filter(Boolean).length : 0;

  if (!nextTournament && champions.length === 0) return null;

  return (
    <section className="mb-10">
      <SectionHeader label="// TOURNAMENTS" viewAllTo="/dice/tournaments" />
      <div className={`grid grid-cols-1 ${nextTournament && champions.length > 0 ? 'sm:grid-cols-2' : ''} gap-3`}>
        {nextTournament && (
          <div className="jk-card overflow-hidden">
            <p className="jk-label px-3 pt-3" style={{ fontSize: 10 }}>NEXT UP</p>
            <TournamentRow tournament={nextTournament} />
          </div>
        )}
        {recentTournament && champions.length > 0 ? (
          <Link to={`/dice/tournament/${recentTournament.id}`} className="jk-card block overflow-hidden">
            <p className="jk-label px-3 pt-3" style={{ fontSize: 10 }}>LATEST CHAMPIONS</p>
            <div className="px-3 py-2.5">
              <div className="flex items-center gap-2">
                <span aria-hidden="true" style={{ fontSize: 22 }}>🏆</span>
                <div className="flex -space-x-2 shrink-0">
                  {champions.map((player) => <PlayerAvatar key={player.user_id} profile={player} size={30} linkToProfile={false} />)}
                </div>
                <p className="text-sm font-semibold truncate">{champions.map((player) => player.display_name).join(' + ')}</p>
              </div>
              <p className="jk-label mt-2 truncate" style={{ fontSize: 10 }}>{recentTournament.name} · {Math.max(recentTournament.completed_games?.length || 0, playedBracketGames)} games · 2-round bracket</p>
            </div>
          </Link>
        ) : (
          <Link to="/dice/tournaments" className="jk-card block p-4 text-sm" style={{ color: 'var(--text-secondary)' }}>
            Browse tournament history →
          </Link>
        )}
      </div>
    </section>
  );
}

export { calculateStreaks, calculateSynergies, HistoricalRecordsSection, CurrentStreaksSection, matchStory, splitTournaments };

function ExperimentalHome({ auth }) {
  const [games, setGames] = useState(null);
  const [elo, setElo] = useState(null);
  const [sinks, setSinks] = useState(null);
  const [selfSinks, setSelfSinks] = useState(null);
  const [tournaments, setTournaments] = useState(null);
  const [liveGames, setLiveGames] = useState(null);
  const [livePredictions, setLivePredictions] = useState({});
  const liveEnabled = auth?.features?.dice_live_referee?.effective === true;
  const currentUserId = auth?.profile?.user_id || auth?.user?.id;

  usePageviewTracking('dice', 'home', '/dice');

  useEffect(() => {
    diceApi.getGames(100).then(setGames).catch(() => setGames([]));
    diceApi.getEloLeaderboard(LEADERBOARD_LIMIT, true).then(setElo).catch(() => setElo([]));
    diceApi.getSinkLeaderboard(LEADERBOARD_LIMIT, false).then(setSinks).catch(() => setSinks([]));
    diceApi.getSelfSinkLeaderboard(LEADERBOARD_LIMIT, false).then(setSelfSinks).catch(() => setSelfSinks([]));
    diceApi.getTournaments(20).then(setTournaments).catch(() => setTournaments([]));
  }, []);

  useEffect(() => {
    if (!liveEnabled || !auth?.token) {
      setLiveGames(null);
      return undefined;
    }
    const loadLiveGames = () => {
      diceApi.getLiveGames(auth.token).then(setLiveGames).catch(() => setLiveGames((current) => current || []));
    };
    loadLiveGames();
    const timer = window.setInterval(loadLiveGames, 15000);
    return () => window.clearInterval(timer);
  }, [auth?.token, liveEnabled]);

  useEffect(() => {
    if (!liveEnabled || !auth?.token || !liveGames?.length) {
      setLivePredictions({});
      return;
    }
    Promise.all(liveGames.map(async (game) => [game.id, await diceApi.getLivePrediction(auth.token, game.id).catch(() => null)]))
      .then((entries) => setLivePredictions(Object.fromEntries(entries)));
  }, [auth?.token, liveEnabled, liveGames]);

  const hasLiveGames = Array.isArray(liveGames) && liveGames.length > 0;
  const liveSection = liveEnabled && hasLiveGames
    ? <LiveHomeSection auth={auth} games={liveGames} predictions={livePredictions} />
    : null;
  const matchesSection = <section className="mb-10">
        <SectionHeader label="// RECENT MATCHES" viewAllTo={hasMore(games) ? '/dice/history' : null} />
        <div className="jk-card overflow-hidden">
          {games === null && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading…</p>}
          {games?.length === 0 && (
            <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>No matches logged yet.</p>
          )}
          {games?.slice(0, HOME_MATCH_LIMIT).map((game) => <GameRow key={game.id} game={game} story={matchStory(game)} />)}
        </div>
      </section>;
  const streaksSection = <CurrentStreaksSection games={games} />;
  const eloSection = <EloSection entries={elo} currentUserId={currentUserId} />;
  const tournamentSection = tournaments === null ? (
        <section className="mb-10"><SectionHeader label="// TOURNAMENTS" viewAllTo="/dice/tournaments" /><div className="jk-card p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading…</div></section>
      ) : <TournamentHighlights tournaments={tournaments} />;
  const sinksSection = <SinkLeadersSection sinks={sinks} selfSinks={selfSinks} currentUserId={currentUserId} />;
  const photosSection = <section>
        <SectionHeader label="// PHOTOS" />
        <PhotoGallery />
      </section>;
  const sections = [liveSection, matchesSection, streaksSection, eloSection, tournamentSection, sinksSection, photosSection];

  return (
    <div className="jk-home max-w-2xl mx-auto px-4 sm:px-6 py-8">
      {sections.map((section, index) => section && <React.Fragment key={index}>{section}</React.Fragment>)}
    </div>
  );
}

export default function Home({ auth }) {
  if (auth?.loading) {
    return <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading…</div>;
  }
  return auth?.features?.dice_live_referee?.effective === true
    ? <ExperimentalHome auth={auth} />
    : <LegacyHome />;
}
