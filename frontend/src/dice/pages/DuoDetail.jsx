import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import PlayerAvatar from '../components/PlayerAvatar.jsx';
import { diceApi } from '../api.js';

export default function DuoDetail({ auth }) {
  const { duoId } = useParams();
  const [detail, setDetail] = useState(null);
  useEffect(() => {
    diceApi
      .getDuoDetail(auth?.token, duoId)
      .then(setDetail)
      .catch(() => setDetail({ error: true }));
  }, [auth?.token, duoId]);
  if (!detail) return <main className="max-w-2xl mx-auto px-4 py-8 text-sm">Loading duo…</main>;
  if (detail.error)
    return (
      <main className="max-w-2xl mx-auto px-4 py-8">
        <p className="jk-display text-3xl">Duo not found</p>
        <Link className="underline text-sm" to="/dice/stats?view=duos">
          Back to Duos →
        </Link>
      </main>
    );
  const { summary } = detail;
  const gameLink = (gameId) => `/dice/game/${gameId}?duo=1`;
  return (
    <main className="max-w-2xl mx-auto px-4 sm:px-6 py-8">
      <Link className="jk-label underline" to="/dice/stats?view=duos">
        ← Duos
      </Link>
      <div className="flex items-center gap-3 mt-5">
        <div className="flex -space-x-3">
          {summary.members.map((member) => (
            <PlayerAvatar key={member.user_id} profile={member} size={52} linkToProfile={false} />
          ))}
        </div>
        <div>
          <h1 className="jk-display text-3xl">{summary.members.map((member) => member.display_name).join(' + ')}</h1>
          <p className="jk-label mt-1">
            {summary.rank ? `Rank #${summary.rank}` : `Provisional · ${summary.games}/3 games`} · {summary.games} games
          </p>
        </div>
      </div>
      <div className="grid grid-cols-3 gap-2 mt-6">
        <div className="jk-card p-3">
          <p className="jk-display text-2xl">{summary.elo}</p>
          <p className="jk-label">ELO</p>
        </div>
        <div className="jk-card p-3">
          <p className="jk-display text-2xl">
            {summary.wins}–{summary.losses}
          </p>
          <p className="jk-label">RECORD</p>
        </div>
        <div className="jk-card p-3">
          <p className="jk-display text-2xl">{Math.round(summary.win_rate * 100)}%</p>
          <p className="jk-label">WIN RATE</p>
        </div>
      </div>
      <p className="text-sm mt-4" style={{ color: 'var(--text-secondary)' }}>
        Current streak {summary.current_streak} · Best streak {summary.best_streak}. Duo ratings start at 1500 with 350 deviation; three ranked 2v2 games place a duo.
      </p>
      <section className="mt-8">
        <p className="jk-label mb-3">// RATING HISTORY</p>
        <div className="jk-card overflow-hidden">
          {detail.rating_history.map((item) => (
            <Link key={`${item.duo_id || summary.duo_id}-${item.game_id}`} to={gameLink(item.game_id)} className="jk-row flex items-center justify-between gap-3 px-3 py-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
              <div>
                <p className="text-sm font-semibold">
                  {item.result === 'win' ? 'Win' : 'Loss'} · {item.score[0]}–{item.score[1]}
                </p>
                <p className="jk-label mt-1">
                  {new Date(item.played_at).toLocaleDateString()} · {item.delta > 0 ? '+' : ''}
                  {item.delta} ELO
                </p>
              </div>
              <span className="text-sm underline">Match</span>
            </Link>
          ))}
          {!detail.rating_history.length && <p className="p-4 text-sm">No ranked games yet.</p>}
        </div>
      </section>
      <section className="mt-8">
        <p className="jk-label mb-3">// HEAD TO HEAD</p>
        <div className="jk-card overflow-hidden">
          {detail.head_to_head.map((record) => (
            <div key={record.opponent_duo_id} className="px-3 py-3" style={{ borderBottom: '1px solid var(--border-subtle)' }}>
              <p className="text-sm font-semibold">{record.opponent_members?.map((member) => member.display_name).join(' + ') || record.opponent_duo_id}</p>
              <p className="text-sm">
                {record.wins}–{record.losses} · {record.games} games
              </p>
              <p className="jk-label mt-1">
                Latest {new Date(record.latest_meeting).toLocaleDateString()} ·{' '}
                {record.game_ids.map((gameId) => (
                  <Link key={gameId} className="underline mr-2" to={gameLink(gameId)}>
                    {gameId.slice(0, 8)}
                  </Link>
                ))}
              </p>
            </div>
          ))}
          {!detail.head_to_head.length && <p className="p-4 text-sm">No opposing duos yet.</p>}
        </div>
      </section>
    </main>
  );
}
