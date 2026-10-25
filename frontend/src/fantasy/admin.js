async function call(apiUrl, token, path, options = {}) {
  const response = await fetch(`${apiUrl}/espn/admin${path}`, {
    ...options, cache: 'no-store',
    headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' },
  });
  if (!response.ok) throw Object.assign(new Error('Settings unavailable'), { status: response.status });
  return response.json();
}
export const checkAdmin = (apiUrl, token) => call(apiUrl, token, '');
export const getLeague = (apiUrl, token, season, signal) => call(apiUrl, token, `/leagues/${season}`, { signal });
export const saveLeague = (apiUrl, token, season, leagueId) => call(apiUrl, token, `/leagues/${season}`, {
  method: 'PUT', body: JSON.stringify({ espn_league_id: leagueId }),
});
