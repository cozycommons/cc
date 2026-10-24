// Team ↔ Dice profile links. Public reads need no auth; claiming uses the Cozy sign-in.
const https = value => (typeof value === 'string' && value.startsWith('https://') ? value : null);

// fresh skips the 60-second public cache right after this visitor changes a link.
export async function fetchOwners(apiUrl, year, signal, fresh = false) {
  if (!apiUrl) return new Map();
  try {
    const query = year ? `?season=${year}` : '';
    const response = await fetch(`${apiUrl}/espn/public/claims${query}`, { signal, ...(fresh && { cache: 'no-store' }) });
    if (!response.ok) return new Map();
    const rows = await response.json();
    return new Map((Array.isArray(rows) ? rows : [])
      .filter(row => Number.isInteger(row?.team_id) && typeof row.display_name === 'string' && row.display_name)
      .map(row => [row.team_id, { name: row.display_name.slice(0, 60), avatar: https(row.avatar_url) }]));
  } catch {
    return new Map();
  }
}

export async function signedInToken() {
  try {
    const { auth } = await import('../supabase');
    return (await auth.getSession())?.access_token || null;
  } catch {
    return null;
  }
}

export async function signIn() {
  const { auth } = await import('../supabase');
  await auth.signInWithGoogle(`${window.location.origin}${window.location.pathname}`);
}

async function call(apiUrl, token, path, options = {}) {
  const response = await fetch(`${apiUrl}${path}`, {
    ...options, headers: { Authorization: `Bearer ${token}`, 'Content-Type': 'application/json', ...options.headers },
  });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw Object.assign(new Error(body?.detail || `HTTP ${response.status}`), { status: response.status, detail: body?.detail });
  return body;
}

export const suggestions = (apiUrl, token) => call(apiUrl, token, '/espn/claims/suggestions');
export const claimTeam = (apiUrl, token, season, teamId) =>
  call(apiUrl, token, '/espn/claims', { method: 'POST', body: JSON.stringify({ season, team_id: teamId }) });
export const releaseTeam = (apiUrl, token, season, teamId) =>
  call(apiUrl, token, `/espn/claims/${season}/${teamId}`, { method: 'DELETE' });
