import React, { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import PlayerAvatar from '../components/PlayerAvatar.jsx';
import { synergyRates, synergyTitle } from '../duoSynergy.js';
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
  const { summary, big_moments: bigMoments } = detail;
  const { synergy } = summary;
  const rates = synergy && synergyRates(synergy);
  const shortenApartNames = summary.members.map((member) => member.display_name).join(' ').length > 16;
  const apart = synergy?.apart.map((record) => {
    const name = summary.members.find((member) => member.user_id === record.user_id)?.display_name || '';
    return `${shortenApartNames ? name.split(/\s+/)[0] : name} ${record.wins}–${record.losses}`;
  }).join(' · ');
  const firstMomentPercent = bigMoments ? Math.round(bigMoments.members[0].share * 100) : 0;
  const gameLink = (gameId) => `/dice/game/${gameId}?duo=1`;
  return (
    <main className="max-w-2xl mx-auto px-4 sm:px-6 py-8">
      <Link className="jk-label underline" to="/dice/stats?view=duos">
        ← Duos
      </Link>
      <div className="flex items-center gap-3 mt-5">
        <div className="flex -space-x-3 shrink-0">
          {summary.members.map((member) => (
            <PlayerAvatar key={member.user_id} profile={member} size={52} linkToProfile={false} />
          ))}
        </div>
        <div className="min-w-0">
          <h1 className="jk-display text-3xl break-words">{summary.members.map((member) => member.display_name).join(' + ')}</h1>
          <p className="jk-label mt-1">
            {summary.rank ? `Rank #${summary.rank}` : `Provisional · ${summary.games}/3 games`} · {summary.games} games
          </p>
        </div>
      </div>
      {synergy && (
        <section className="jk-card p-4 mt-6" aria-label="Duo synergy">
          <h2 className="jk-label">{synergyTitle(synergy)}</h2>
          <dl className="grid grid-cols-2 gap-3 mt-2">
            <div className="flex flex-col-reverse justify-end">
              <dt className="jk-label mt-1" style={{ color: 'var(--text-secondary)' }}>Won together · {synergy.wins}–{synergy.losses}</dt>
              <dd className="jk-display text-3xl tabular-nums">{rates.together}%</dd>
            </div>
            <div className="flex flex-col-reverse justify-end">
              <dt className="jk-label mt-1" style={{ color: 'var(--text-secondary)' }}>Expected</dt>
              <dd className="jk-display text-3xl tabular-nums" style={{ color: 'var(--text-secondary)' }}>{rates.expected}%</dd>
            </div>
          </dl>
          {apart && <p className="jk-label mt-3 break-words" style={{ color: 'var(--text-secondary)' }}>Apart: {apart}</p>}
        </section>
      )}
      {bigMoments && (
        <section className="jk-card p-4 mt-4" aria-label="Big moments">
          <h2 className="jk-display text-xl">Big moments</h2>
          <p className="text-sm mt-1" style={{ color: 'var(--text-secondary)' }}>Share of big swings</p>
          <div className="grid grid-cols-2 gap-3 text-sm mt-3">
            {bigMoments.members.map((record, index) => (
              <p key={record.user_id} className="min-w-0 break-words">
                {summary.members.find((member) => member.user_id === record.user_id)?.display_name} · {index === 0 ? firstMomentPercent : 100 - firstMomentPercent}%
              </p>
            ))}
          </div>
          <div className="flex h-3 rounded overflow-hidden mt-2" aria-hidden="true">
            {bigMoments.members.map((record, index) => (
              <div key={record.user_id} style={{ width: `${record.share * 100}%`, background: index === 0 ? 'var(--team1-color)' : 'var(--team2-color)' }} />
            ))}
          </div>
        </section>
      )}
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
