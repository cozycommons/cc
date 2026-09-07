import React, { Suspense, lazy } from 'react';
import { Navigate, Routes, Route } from 'react-router-dom';
import DiceHeader from './DiceHeader.jsx';
import { useDiceAuth } from './useDiceAuth.js';
import './dice-theme.css';

const Home = lazy(() => import('./pages/Home.jsx'));
const Players = lazy(() => import('./pages/Players.jsx'));
const MatchHistory = lazy(() => import('./pages/MatchHistory.jsx'));
const EloLeaderboard = lazy(() => import('./pages/EloLeaderboard.jsx'));
const SelfSinkLeaderboard = lazy(() => import('./pages/SelfSinkLeaderboard.jsx'));
const SinkLeaderboard = lazy(() => import('./pages/SinkLeaderboard.jsx'));
const PlayerProfile = lazy(() => import('./pages/PlayerProfile.jsx'));
const GameDetail = lazy(() => import('./pages/GameDetail.jsx'));
const LogMatch = lazy(() => import('./pages/LogMatch.jsx'));
const EloExplainer = lazy(() => import('./pages/EloExplainer.jsx'));
const Tournaments = lazy(() => import('./pages/Tournaments.jsx'));
const TournamentDetail = lazy(() => import('./pages/TournamentDetail.jsx'));
const TournamentForm = lazy(() => import('./pages/TournamentForm.jsx'));
const LiveLobby = lazy(() => import('./pages/LiveLobby.jsx'));
const LiveGame = lazy(() => import('./pages/LiveGame.jsx'));
const VirtualDice = lazy(() => import('./pages/VirtualDice.jsx'));
const Stats = lazy(() => import('./pages/Stats.jsx'));

export default function DiceApp() {
  const auth = useDiceAuth();
  const experimentalHomeEnabled = auth.features?.dice_live_referee?.effective === true;

  return (
    <div className="jk-dice min-h-screen">
      <DiceHeader auth={auth} />
      <Suspense fallback={<div className="p-6 text-center">Loading…</div>}>
        <Routes>
          <Route index element={<Home auth={auth} />} />
          <Route path="players" element={<Players />} />
          <Route path="history" element={<MatchHistory />} />
          <Route path="stats" element={auth.loading ? null : (experimentalHomeEnabled ? <Stats /> : <Navigate replace to="/dice" />)} />
          <Route path="leaderboard/elo" element={<EloLeaderboard auth={auth} />} />
          <Route path="leaderboard/self-sinks" element={<SelfSinkLeaderboard auth={auth} />} />
          <Route path="leaderboard/sinks" element={<SinkLeaderboard auth={auth} />} />
          <Route path="profile/:userId" element={<PlayerProfile auth={auth} />} />
          <Route path="game/:gameId" element={<GameDetail auth={auth} />} />
          <Route path="log" element={<LogMatch auth={auth} />} />
          <Route path="game/:gameId/edit" element={<LogMatch auth={auth} editMode />} />
          <Route path="elo-explained" element={<EloExplainer />} />
          <Route path="tournaments" element={<Tournaments auth={auth} />} />
          <Route path="tournament/new" element={<TournamentForm auth={auth} />} />
          <Route path="tournament/:tournamentId" element={<TournamentDetail auth={auth} />} />
          <Route path="tournament/:tournamentId/virtual" element={<VirtualDice auth={auth} />} />
          <Route path="tournament/:tournamentId/edit" element={<TournamentForm auth={auth} editMode />} />
          <Route path="live" element={<LiveLobby auth={auth} />} />
          <Route path="live/:matchId" element={<LiveGame auth={auth} />} />
        </Routes>
      </Suspense>
    </div>
  );
}
