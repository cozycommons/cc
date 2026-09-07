import React from 'react';
import { Navigate, Routes, Route } from 'react-router-dom';
import DiceHeader from './DiceHeader.jsx';
import { useDiceAuth } from './useDiceAuth.js';
import Home from './pages/Home.jsx';
import Players from './pages/Players.jsx';
import MatchHistory from './pages/MatchHistory.jsx';
import EloLeaderboard from './pages/EloLeaderboard.jsx';
import SelfSinkLeaderboard from './pages/SelfSinkLeaderboard.jsx';
import SinkLeaderboard from './pages/SinkLeaderboard.jsx';
import PlayerProfile from './pages/PlayerProfile.jsx';
import GameDetail from './pages/GameDetail.jsx';
import LogMatch from './pages/LogMatch.jsx';
import EloExplainer from './pages/EloExplainer.jsx';
import Tournaments from './pages/Tournaments.jsx';
import TournamentDetail from './pages/TournamentDetail.jsx';
import TournamentForm from './pages/TournamentForm.jsx';
import LiveLobby from './pages/LiveLobby.jsx';
import LiveGame from './pages/LiveGame.jsx';
import VirtualDice from './pages/VirtualDice.jsx';
import Stats from './pages/Stats.jsx';
import './dice-theme.css';

export default function DiceApp() {
  const auth = useDiceAuth();
  const experimentalHomeEnabled = auth.features?.dice_live_referee?.effective === true;

  return (
    <div className="jk-dice min-h-screen">
      <DiceHeader auth={auth} />
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
    </div>
  );
}
