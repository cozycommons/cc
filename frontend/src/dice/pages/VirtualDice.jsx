import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { diceApi } from '../api.js';

const clientPickId = () => globalThis.crypto?.randomUUID?.() || `pick-${Date.now()}`;
const percent = (millionths) => `${Math.round(Number(millionths) / 10000)}%`;

function teamName(game, selection) {
  if (!game) return selection;
  return (game.teams?.[selection] || [])
    .map((id) => game.player_names?.[id] || id.slice(-4))
    .join(' + ') || selection;
}

function MarketCard({ market, game, picks, token, tournamentId, onChanged }) {
  const [stake, setStake] = useState('100');
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  const [attempt, setAttempt] = useState(null);
  const [confirmedPick, setConfirmedPick] = useState(null);
  const ownPicks = picks.filter((pick) => pick.market_id === market.id);
  if (confirmedPick && !ownPicks.some((pick) => pick.id === confirmedPick.id)) ownPicks.unshift(confirmedPick);
  const canPick = market.status === 'open' && ownPicks.length === 0;

  const place = async (selection) => {
    const amount = Number(stake);
    if (!Number.isInteger(amount) || amount <= 0) {
      setError('Enter a whole-number stake.');
      return;
    }
    const pending = attempt?.selection === selection && attempt?.stake === amount
      ? attempt
      : { id: clientPickId(), selection, stake: amount };
    setAttempt(pending);
    setBusy(selection);
    setError('');
    try {
      const placedPick = await diceApi.placeVirtualPick(token, tournamentId, market.id, {
        client_pick_id: pending.id, selection, stake: amount,
      });
      setConfirmedPick(placedPick);
      setAttempt(null);
      await onChanged();
    } catch (requestError) {
      setError(requestError.message || 'Pick was not accepted.');
    } finally {
      setBusy('');
    }
  };

  return (
    <article className="jk-card p-4">
      <div className="flex items-center justify-between gap-3">
        <p className="jk-label">MATCH WINNER</p>
        <p className="jk-label">{market.status}</p>
      </div>
      <Link to={`/dice/live/${market.live_match_id}`} className="inline-block mt-2 text-xs underline">
        Watch or referee this game
      </Link>
      {canPick && (
        <label className="jk-label block mt-4" htmlFor={`stake-${market.id}`}>
          Stake
          <Input id={`stake-${market.id}`} inputMode="numeric" value={stake} disabled={Boolean(attempt)} onChange={(event) => setStake(event.target.value)} className="mt-1 h-11 text-base" />
        </label>
      )}
      <div className="grid grid-cols-2 gap-2 mt-3">
        {Object.entries(market.selections).map(([selection, terms]) => {
          const amount = Number(stake) || 0;
          const payout = Math.floor(amount * 1000000 / terms.probability_millionths);
          return (
            <button
              type="button"
              key={selection}
              disabled={!canPick || Boolean(busy) || Boolean(attempt && attempt.selection !== selection)}
              onClick={() => place(selection)}
              className="text-left rounded-md border p-3 disabled:opacity-70"
              style={{ borderColor: 'var(--border-default)', background: 'var(--surface-card)' }}
            >
              <span className="block font-semibold leading-tight">{teamName(game, selection)}</span>
              <span className="block mt-2 text-sm tabular-nums" style={{ color: 'var(--text-secondary)' }}>
                {percent(terms.probability_millionths)} chance
              </span>
              {canPick && <span className="block mt-1 text-xs" style={{ color: 'var(--text-tertiary)' }}>Total return {payout} Dice</span>}
              {attempt?.selection === selection && !busy && <span className="block mt-1 text-xs">Retry same pick safely</span>}
              {busy === selection && <span className="block mt-1 text-xs">Placing…</span>}
            </button>
          );
        })}
      </div>
      {ownPicks.map((pick) => (
        <div key={pick.id} className="mt-3 pt-3 text-sm" style={{ borderTop: '1px solid var(--border-subtle)' }}>
          <div className="flex items-start justify-between gap-2">
            <span className="font-semibold min-w-0">{pick.stake} on {teamName(game, pick.selection)}</span>
            <span className="jk-label shrink-0">{pick.status}</span>
          </div>
          <p className="mt-1 text-xs" style={{ color: 'var(--text-tertiary)' }}>
            Locked return {pick.potential_return} Dice
          </p>
        </div>
      ))}
      {error && <p role="alert" className="mt-3 text-sm" style={{ color: 'var(--state-danger)' }}>{error} {attempt && 'Tap the same team to retry without duplicating it.'}</p>}
    </article>
  );
}

export default function VirtualDice({ auth }) {
  const { tournamentId } = useParams();
  const [bankroll, setBankroll] = useState(null);
  const [markets, setMarkets] = useState([]);
  const [picks, setPicks] = useState([]);
  const [leaderboard, setLeaderboard] = useState([]);
  const [games, setGames] = useState({});
  const [liveGames, setLiveGames] = useState([]);
  const [enrolledIds, setEnrolledIds] = useState(new Set());
  const [loading, setLoading] = useState(true);
  const [opening, setOpening] = useState('');
  const [error, setError] = useState('');
  const [leaderboardError, setLeaderboardError] = useState('');
  const latestLoad = useRef(0);

  const load = useCallback(async () => {
    if (!auth.token) return;
    const requestId = latestLoad.current + 1;
    latestLoad.current = requestId;
    setError('');
    setLeaderboardError('');
    try {
      const wallet = await diceApi.openVirtualBankroll(auth.token, tournamentId);
      const [currentMarkets, currentPicks, standingsResult, ongoing, tournament] = await Promise.all([
        diceApi.getVirtualMarkets(auth.token, tournamentId),
        diceApi.getVirtualPicks(auth.token, tournamentId),
        diceApi.getVirtualLeaderboard(auth.token, tournamentId)
          .then((standings) => ({ standings }))
          .catch((standingsError) => ({ standingsError })),
        diceApi.getLiveGames(auth.token),
        diceApi.getTournament(tournamentId),
      ]);
      const ongoingById = Object.fromEntries(ongoing.map((game) => [game.id, game]));
      const missingIds = [...new Set(currentMarkets.map((market) => market.live_match_id).filter((id) => !ongoingById[id]))];
      const historical = await Promise.all(missingIds.map((id) => diceApi.getLiveGame(auth.token, id)));
      if (requestId !== latestLoad.current) return;
      setBankroll(wallet.balance);
      setMarkets(currentMarkets);
      setPicks(currentPicks);
      if (standingsResult.standingsError) {
        setLeaderboardError('Standings are temporarily unavailable.');
      } else {
        setLeaderboard(standingsResult.standings);
      }
      setLiveGames(ongoing);
      setEnrolledIds(new Set(tournament.enrolled_players.map((player) => player.user_id)));
      setGames({ ...ongoingById, ...Object.fromEntries(historical.map((game) => [game.id, game])) });
    } catch (requestError) {
      if (requestId !== latestLoad.current) return;
      setError(requestError.message || 'Virtual Dice is unavailable.');
    } finally {
      if (requestId === latestLoad.current) setLoading(false);
    }
  }, [auth.token, tournamentId]);

  useEffect(() => { load(); }, [load]);

  useEffect(() => {
    if (markets.length > 0 && markets.every((market) => market.status === 'settled')) return undefined;
    const timer = window.setInterval(load, 15000);
    return () => window.clearInterval(timer);
  }, [load, markets]);

  const marketMatchIds = new Set(markets.map((market) => market.live_match_id));
  const eligible = liveGames.filter((game) => game.version === 0 && game.status === 'active'
    && game.team_order.flatMap((team) => game.teams[team]).every((playerId) => enrolledIds.has(playerId))
    && !marketMatchIds.has(game.id));

  const openMarket = async (matchId) => {
    setOpening(matchId);
    setError('');
    try {
      await diceApi.createVirtualMarket(auth.token, tournamentId, matchId);
      await load();
    } catch (requestError) {
      setError(requestError.message || 'Could not open predictions for this game.');
    } finally {
      setOpening('');
    }
  };

  return (
    <main className="max-w-xl mx-auto px-4 pt-6 pb-24">
      <Link to={`/dice/tournament/${tournamentId}`} className="text-sm underline">Back to tournament</Link>
      <div className="flex items-end justify-between gap-3 mt-5 mb-5">
        <div><p className="jk-label">VIRTUAL DICE</p><h1 className="jk-display text-4xl">Match picks</h1></div>
        {bankroll !== null && <div className="text-right"><p className="jk-display text-3xl tabular-nums">{bankroll}</p><p className="jk-label">DICE</p></div>}
      </div>

      {loading && <p role="status" className="jk-label py-8 text-center">Loading your Dice…</p>}
      {error && <div role="alert" className="jk-card p-3 mb-4 text-sm flex items-center justify-between gap-3" style={{ color: 'var(--state-danger)' }}><span>{error}</span><Button size="sm" variant="outline" onClick={load}>Retry</Button></div>}

      {!loading && eligible.length > 0 && (
        <section className="mb-5">
          <p className="jk-label mb-2">READY TO OPEN</p>
          {eligible.map((game) => (
            <div key={game.id} className="jk-card p-4 flex items-center justify-between gap-3">
              <p className="text-sm font-semibold">{game.team_order.map((team) => teamName(game, team)).join(' vs ')}</p>
              <Button size="sm" disabled={opening === game.id} onClick={() => openMarket(game.id)}>{opening === game.id ? 'Opening…' : 'Open picks'}</Button>
            </div>
          ))}
        </section>
      )}

      <section className="space-y-3">
        {markets.map((market) => <MarketCard key={market.id} market={market} game={games[market.live_match_id]} picks={picks} token={auth.token} tournamentId={tournamentId} onChanged={load} />)}
        {!loading && markets.length === 0 && eligible.length === 0 && !error && (
          <div className="jk-card p-6 text-center"><p className="font-semibold">No pregame picks yet</p><p className="text-sm mt-2" style={{ color: 'var(--text-secondary)' }}>Start a live game before the first throw to open a market.</p></div>
        )}
      </section>

      {!loading && !error && (
        <section className="jk-card p-4 mt-5" aria-labelledby="virtual-standings-heading">
          <p id="virtual-standings-heading" className="jk-label mb-3">TOURNAMENT STANDINGS</p>
          {leaderboardError ? (
            <div className="flex items-center justify-between gap-3 text-sm" style={{ color: 'var(--text-secondary)' }}>
              <span>{leaderboardError}</span>
              <Button size="sm" variant="outline" onClick={load}>Retry</Button>
            </div>
          ) : leaderboard.length === 0 ? (
            <p className="text-sm" style={{ color: 'var(--text-secondary)' }}>No tournament balances yet.</p>
          ) : leaderboard.map((player) => (
            <div key={player.user_id} className="flex items-center gap-3 py-2 text-sm" style={{ borderTop: player.rank === 1 ? 'none' : '1px solid var(--border-subtle)' }}>
              <span className="w-7 tabular-nums" style={{ color: 'var(--text-tertiary)' }}>#{player.rank}</span>
              <span className="font-semibold min-w-0 flex-1 truncate">
                {player.display_name}
                {player.user_id === auth.user?.id && <span className="jk-label ml-2">YOU</span>}
              </span>
              <span className="font-semibold tabular-nums">{player.balance} Dice</span>
            </div>
          ))}
        </section>
      )}
    </main>
  );
}
