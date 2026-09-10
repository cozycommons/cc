import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { diceApi } from '../api.js';
import PlayerAvatar from '../components/PlayerAvatar.jsx';
import { calculateStreaks, rankedStreakGames } from './Home.jsx';

function EvidenceGame({ game, userId, number }) {
  const player = game.players?.find((candidate) => candidate.user_id === userId);
  const teammates = (game.players || []).filter((candidate) => candidate.team === player?.team && candidate.user_id !== userId).map((candidate) => candidate.display_name).join(' + ') || 'No teammate';
  const opponents = (game.players || []).filter((candidate) => candidate.team !== player?.team).map((candidate) => candidate.display_name).join(' + ') || 'Opponents unknown';
  const score = player?.team === 2 ? `${game.team2_score}–${game.team1_score}` : `${game.team1_score}–${game.team2_score}`;
  return <Link to={`/dice/game/${game.id}`} className="jk-streak-game"><span className="jk-streak-game-number">{number}</span><div className="min-w-0 flex-1"><div className="flex items-center justify-between gap-3"><span className="text-sm font-semibold">{score}</span><span className="jk-label">{new Date(game.played_at).toLocaleDateString()}</span></div><p className="jk-label mt-1 truncate">with {teammates} · vs {opponents}</p></div><span className="jk-streak-game-win">W</span></Link>;
}

export default function StreakDetail() {
  const { userId } = useParams();
  const [games, setGames] = useState(null);
  useEffect(() => { (typeof diceApi.getAllGames === 'function' ? diceApi.getAllGames() : diceApi.getGames(200)).then(setGames).catch(() => setGames([])); }, []);
  if (!games) return <main className="max-w-2xl mx-auto px-4 py-8 text-sm">Loading streak…</main>;
  const record = calculateStreaks(games).find((candidate) => candidate.user_id === userId);
  if (!record) return <main className="max-w-2xl mx-auto px-4 py-8"><p className="jk-display text-3xl">Streak not found</p><Link className="underline text-sm" to="/dice/stats?view=streaks">Back to Streaks →</Link></main>;
  const currentGames = rankedStreakGames(games, record.current_game_ids);
  const bestGames = rankedStreakGames(games, record.best_game_ids);
  const currentIsBest = currentGames.length > 0
    && currentGames.length === bestGames.length
    && currentGames.every((game, index) => game.id === bestGames[index]?.id);
  const run = (label, runGames, empty) => (
    <section className="mt-8">
      <p className="jk-label mb-3">// {label}</p>
      <div className="jk-card jk-streak-run overflow-hidden">
        {runGames.map((game, index) => <EvidenceGame key={game.id} game={game} userId={userId} number={index + 1} />)}
        {!runGames.length && <p className="p-4 text-sm">{empty}</p>}
      </div>
    </section>
  );
  return (
    <main className="max-w-2xl mx-auto px-4 sm:px-6 py-8">
      <Link className="jk-label underline" to="/dice/stats?view=streaks">← Streaks</Link>
      <section className="jk-streak-detail-hero mt-5">
        <div className="flex items-center gap-3 min-w-0">
          <PlayerAvatar profile={record} size={64} linkToProfile={false} />
          <div className="min-w-0">
            <p className="jk-label">WIN STREAK</p>
            <h1 className="jk-display text-3xl truncate">{record.display_name}</h1>
          </div>
        </div>
        <div className="jk-streak-detail-scores">
          <div><strong>{record.current}</strong><span>ACTIVE</span></div>
          <div><strong>{record.best}</strong><span>BEST</span></div>
        </div>
      </section>
      {currentIsBest
        ? run('CURRENT & BEST RUN', currentGames, 'No recorded run yet.')
        : <>{currentGames.length > 0 && run('ACTIVE STREAK', currentGames, 'No active streak.')}{run('BEST RUN', bestGames, 'No recorded run yet.')}</>}
    </main>
  );
}
