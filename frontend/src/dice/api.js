import { api, getUrl } from '../api.js';
import { sendLiveCommandWithAdaptiveHedge } from './liveCommandHedge.js';

function authHeaders(token) {
  return token ? { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' } : {};
}

export class DiceLiveApiError extends Error {
  constructor(status, detail) {
    const normalized = typeof detail === 'string' ? { code: detail } : (detail || {});
    super(normalized.message || normalized.code || `Live request failed (${status})`);
    this.name = 'DiceLiveApiError';
    this.status = status;
    this.detail = normalized;
  }
}

async function liveRequest(token, method, path, body, { signal, headers = {}, keepalive = false } = {}) {
  const response = await fetch(`${getUrl()}${path}`, {
    method,
    headers: { ...authHeaders(token), ...headers },
    signal,
    keepalive,
    ...(method === 'GET' ? { cache: 'no-store' } : {}),
    ...(body === undefined ? {} : { body: JSON.stringify(body) }),
  });
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new DiceLiveApiError(response.status, payload.detail);
  return payload;
}

class DiceApiClient {
  // Private live referee API. Every mutating response is server canonical.
  getLiveGames(token) {
    return liveRequest(token, 'GET', '/dice/live/games');
  }

  createLiveGame(token, payload, idempotencyKey) {
    return liveRequest(token, 'POST', '/dice/live/games', payload, {
      headers: { 'Idempotency-Key': idempotencyKey },
    });
  }

  getLiveGame(token, matchId) {
    return liveRequest(token, 'GET', `/dice/live/games/${matchId}`);
  }

  updateLiveSettings(token, matchId, ranked) {
    return liveRequest(token, 'PUT', `/dice/live/games/${matchId}/settings`, { ranked });
  }

  getLivePrediction(token, matchId) {
    return liveRequest(token, 'GET', `/dice/live/games/${matchId}/prediction`);
  }

  getLivePulse(token, matchId) {
    return liveRequest(token, 'GET', `/dice/live/games/${matchId}/pulse`);
  }

  joinLiveGame(token, matchId) {
    return liveRequest(token, 'PUT', `/dice/live/games/${matchId}/referees/me`);
  }

  leaveLiveGame(token, matchId) {
    return liveRequest(token, 'DELETE', `/dice/live/games/${matchId}/referees/me`);
  }

  sendLiveCommand(token, matchId, command) {
    return sendLiveCommandWithAdaptiveHedge(({ attempt, signal }) => (
      liveRequest(token, 'POST', `/dice/live/games/${matchId}/commands`, command, {
        signal,
        headers: {
          'X-Dice-Live-Attempt': attempt,
          'X-Dice-Live-Operation': command.client_command_id,
        },
      })
    ), {
      onTelemetry: (metric) => {
        void liveRequest(
          token,
          'POST',
          `/dice/live/games/${matchId}/command-metrics`,
          { operation_id: command.client_command_id, ...metric },
          { keepalive: true },
        ).catch(() => {});
      },
    });
  }

  openVirtualBankroll(token, tournamentId) {
    return liveRequest(token, 'POST', `/dice/virtual/tournaments/${tournamentId}/bankroll`);
  }

  getVirtualMarkets(token, tournamentId) {
    return liveRequest(token, 'GET', `/dice/virtual/tournaments/${tournamentId}/markets`);
  }

  getVirtualPicks(token, tournamentId) {
    return liveRequest(token, 'GET', `/dice/virtual/tournaments/${tournamentId}/picks`);
  }

  getVirtualLeaderboard(token, tournamentId) {
    return liveRequest(token, 'GET', `/dice/virtual/tournaments/${tournamentId}/leaderboard`);
  }

  createVirtualMarket(token, tournamentId, liveMatchId) {
    return liveRequest(token, 'POST', `/dice/virtual/tournaments/${tournamentId}/markets`, { live_match_id: liveMatchId });
  }

  placeVirtualPick(token, tournamentId, marketId, payload) {
    return liveRequest(token, 'POST', `/dice/virtual/tournaments/${tournamentId}/markets/${marketId}/picks`, payload);
  }

  // Profiles
  getMyProfile(token) {
    return api.get('/dice/me', token);
  }

  updateMyProfile(token, profileData) {
    return api.request('PUT', '/dice/me', profileData, { headers: authHeaders(token) });
  }

  searchProfiles(query, limit = 20) {
    const params = new URLSearchParams({ q: query || '', limit: String(limit) });
    return api.get(`/dice/profiles/search?${params.toString()}`);
  }

  getProfile(userId, token) {
    return api.get(`/dice/profiles/${userId}`, token);
  }

  getProfileGames(userId, limit = 50) {
    return api.get(`/dice/profiles/${userId}/games?limit=${limit}`);
  }

  getRatingProgress(userId) {
    return api.get(`/dice/profiles/${userId}/rating-progress`);
  }

  getDuoLadder(token, limit = 100, homepageEligible = false) {
    return api.get(`/dice/stats/duos?limit=${limit}&homepage_eligible=${homepageEligible}`, token);
  }

  getDuoDetail(token, duoId) {
    return api.get(`/dice/stats/duos/${encodeURIComponent(duoId)}`, token);
  }

  // Leaderboards
  getEloLeaderboard(limit = 5, includeProvisional = false) {
    return api.get(`/dice/leaderboard/elo?limit=${limit}&include_provisional=${includeProvisional}`);
  }

  getSelfSinkLeaderboard(limit = 5, nonzeroOnly = true) {
    return api.get(`/dice/leaderboard/self-sinks?limit=${limit}&nonzero_only=${nonzeroOnly}`);
  }

  getSinkLeaderboard(limit = 5, nonzeroOnly = true) {
    return api.get(`/dice/leaderboard/sinks?limit=${limit}&nonzero_only=${nonzeroOnly}`);
  }

  // Games
  getGames(limit = 5, offset = 0) {
    return api.get(`/dice/games?limit=${limit}&offset=${offset}`);
  }

  async getAllGames(pageSize = 200) {
    const all = [];
    let offset = 0;
    while (true) {
      const page = await this.getGames(pageSize, offset);
      all.push(...page);
      if (page.length < pageSize) return all;
      offset += pageSize;
    }
  }

  getGame(id, includeDuoOnly = false, token = null) {
    const query = includeDuoOnly ? '?duo=1' : '';
    return api.get(`/dice/games/${id}${query}`, token);
  }

  createGame(token, gameData, idempotencyKey) {
    return api.request('POST', '/dice/games', gameData, {
      headers: { ...authHeaders(token), 'Idempotency-Key': idempotencyKey },
    });
  }

  updateGame(token, id, gameData) {
    return api.request('PUT', `/dice/games/${id}`, gameData, { headers: authHeaders(token) });
  }

  deleteGame(token, id, idempotencyKey) {
    return api.request('DELETE', `/dice/games/${id}`, null, {
      headers: { ...authHeaders(token), 'Idempotency-Key': idempotencyKey },
    });
  }

  // Photos
  getPhotos(limit = 100) {
    return api.get(`/dice/photos?limit=${limit}`);
  }

  // Comments
  getComments(gameId) {
    return api.get(`/dice/games/${gameId}/comments`);
  }

  postComment(token, gameId, body, imageUrl) {
    return api.post(`/dice/games/${gameId}/comments`, { body, image_url: imageUrl }, token);
  }

  deleteComment(token, commentId) {
    return api.request('DELETE', `/dice/comments/${commentId}`, null, { headers: authHeaders(token) });
  }

  // Tournaments
  getTournaments(limit = 20) {
    return api.get(`/dice/tournaments?limit=${limit}`);
  }

  getTournament(id) {
    return api.get(`/dice/tournaments/${id}`);
  }

  createTournament(token, tournamentData) {
    return api.post('/dice/tournaments', tournamentData, token);
  }

  updateTournament(token, id, tournamentData) {
    return api.request('PUT', `/dice/tournaments/${id}`, tournamentData, { headers: authHeaders(token) });
  }

  deleteTournament(token, id) {
    return api.request('DELETE', `/dice/tournaments/${id}`, null, { headers: authHeaders(token) });
  }

  enrollInTournament(token, id, userId = null) {
    return api.request('POST', `/dice/tournaments/${id}/enroll`, userId ? { user_id: userId } : null, {
      headers: authHeaders(token),
    });
  }

  unenrollFromTournament(token, id) {
    return api.request('DELETE', `/dice/tournaments/${id}/enroll`, null, { headers: authHeaders(token) });
  }

  // Scheduled matches
  addScheduledMatch(token, tournamentId, matchData) {
    return api.post(`/dice/tournaments/${tournamentId}/matches`, matchData, token);
  }

  updateScheduledMatch(token, tournamentId, matchId, matchData) {
    return api.request('PUT', `/dice/tournaments/${tournamentId}/matches/${matchId}`, matchData, {
      headers: authHeaders(token),
    });
  }

  deleteScheduledMatch(token, tournamentId, matchId) {
    return api.request('DELETE', `/dice/tournaments/${tournamentId}/matches/${matchId}`, null, {
      headers: authHeaders(token),
    });
  }

  // Finalists & bracket
  addFinalist(token, tournamentId, userId) {
    return api.post(`/dice/tournaments/${tournamentId}/finalists`, { user_id: userId }, token);
  }

  removeFinalist(token, tournamentId, userId) {
    return api.request('DELETE', `/dice/tournaments/${tournamentId}/finalists/${userId}`, null, {
      headers: authHeaders(token),
    });
  }

  resolveBracketMatch(token, tournamentId, slotId, gameId) {
    return api.post(`/dice/tournaments/${tournamentId}/bracket/${slotId}/resolve`, { game_id: gameId }, token);
  }

  setBracketTeams(token, tournamentId, teamsData) {
    return api.request('PUT', `/dice/tournaments/${tournamentId}/bracket/teams`, teamsData, {
      headers: authHeaders(token),
    });
  }
}

export const diceApi = new DiceApiClient();
