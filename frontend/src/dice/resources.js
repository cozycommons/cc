import { diceApi } from './api.js';
import { findDiceResource } from './resourceCache.js';

// Home, Stats and the streak pages all need the full public history; sharing
// one cache key means only the first of them waits for it.
export const ALL_GAMES_KEY = 'games:all';

export function loadAllGames() {
  return typeof diceApi.getAllGames === 'function' ? diceApi.getAllGames() : diceApi.getGames(200);
}

// A game already listed on another page (Home, history, a profile) can render
// its detail view at once while the detail request refreshes it.
export function findListedGame(gameId) {
  return findDiceResource((data) => (
    Array.isArray(data) ? data.find((game) => game?.id === gameId && Array.isArray(game.players)) : undefined
  ));
}
