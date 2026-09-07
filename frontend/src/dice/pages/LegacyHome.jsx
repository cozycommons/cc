import React, { useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { diceApi } from '../api.js';
import GameRow from '../components/GameRow.jsx';
import LeaderboardRow from '../components/LeaderboardRow.jsx';
import PhotoGallery from '../components/PhotoGallery.jsx';
import TournamentRow from '../components/TournamentRow.jsx';
import { usePageviewTracking } from '../../analytics/usePageviewTracking';

const PREVIEW_LIMIT = 5;

function hasMore(list) {
  return Array.isArray(list) && list.length >= PREVIEW_LIMIT;
}

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

export default function LegacyHome() {
  const [games, setGames] = useState(null);
  const [elo, setElo] = useState(null);
  const [sinks, setSinks] = useState(null);
  const [selfSinks, setSelfSinks] = useState(null);
  const [tournaments, setTournaments] = useState(null);

  usePageviewTracking('dice', 'home', '/dice');

  useEffect(() => {
    diceApi.getGames(PREVIEW_LIMIT).then(setGames).catch(() => setGames([]));
    diceApi.getEloLeaderboard(PREVIEW_LIMIT).then(setElo).catch(() => setElo([]));
    diceApi.getSinkLeaderboard(PREVIEW_LIMIT, true).then(setSinks).catch(() => setSinks([]));
    diceApi.getSelfSinkLeaderboard(PREVIEW_LIMIT, true).then(setSelfSinks).catch(() => setSelfSinks([]));
    diceApi.getTournaments(PREVIEW_LIMIT).then(setTournaments).catch(() => setTournaments([]));
  }, []);

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8">
      <section className="mb-10">
        <SectionHeader label="// TOURNAMENTS" viewAllTo={hasMore(tournaments) ? '/dice/tournaments' : null} />
        <div className="jk-card overflow-hidden">
          {tournaments === null && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading…</p>}
          {tournaments?.length === 0 && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>No tournaments scheduled yet.</p>}
          {tournaments?.map((tournament) => <TournamentRow key={tournament.id} tournament={tournament} />)}
        </div>
      </section>

      <section className="mb-10">
        <SectionHeader label="// RECENT MATCHES" viewAllTo={hasMore(games) ? '/dice/history' : null} />
        <div className="jk-card overflow-hidden">
          {games === null && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading…</p>}
          {games?.length === 0 && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>No matches logged yet.</p>}
          {games?.map((game) => <GameRow key={game.id} game={game} />)}
        </div>
      </section>

      <section className="mb-10">
        <SectionHeader label="// ELO LEADERBOARD" viewAllTo="/dice/leaderboard/elo" />
        <div className="jk-card overflow-hidden">
          {elo === null && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading…</p>}
          {elo?.length === 0 && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>No ranked players yet.</p>}
          {elo?.map((profile) => (
            <LeaderboardRow key={profile.user_id} rank={profile.rank} tied={profile.is_tied} profile={profile} value={profile.elo_rating} valueLabel="ELO" />
          ))}
        </div>
        <Link to="/dice/elo-explained" style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-tertiary)' }} className="inline-block mt-2">
          How does ELO work? →
        </Link>
      </section>

      <section className="mb-10">
        <SectionHeader label="// SINK LEADERBOARD" viewAllTo={hasMore(sinks) ? '/dice/leaderboard/sinks' : null} />
        <div className="jk-card overflow-hidden">
          {sinks === null && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading…</p>}
          {sinks?.length === 0 && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Nobody's sunk anything yet.</p>}
          {sinks?.map((profile, index) => (
            <LeaderboardRow key={profile.user_id} rank={index + 1} profile={profile} value={profile.sinks} valueLabel="sinks" />
          ))}
        </div>
      </section>

      <section className="mb-10">
        <SectionHeader label="// SELF SINK LEADERBOARD" viewAllTo={hasMore(selfSinks) ? '/dice/leaderboard/self-sinks' : null} />
        <div className="jk-card overflow-hidden">
          {selfSinks === null && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading…</p>}
          {selfSinks?.length === 0 && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Nobody's self-sunk yet. 🎉</p>}
          {selfSinks?.map((profile, index) => (
            <LeaderboardRow key={profile.user_id} rank={index + 1} profile={profile} value={profile.self_sinks} valueLabel="sinks" />
          ))}
        </div>
      </section>

      <section>
        <SectionHeader label="// PHOTOS" />
        <PhotoGallery />
      </section>
    </div>
  );
}
