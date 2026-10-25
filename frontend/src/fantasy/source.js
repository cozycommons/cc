// Interim snapshot host until the Cozy upload route is configured in production.
export const FALLBACK_URL = 'https://gist.githubusercontent.com/homatthew/a417a860db31c1a9e5c13b08338b7a65/raw/fantasy-latest.json';

const TIMEOUT_MS = 8000;
const MODES = ['projections', 'balanced', 'hot'];
const MANAGER = /^[A-Za-z][A-Za-z '\-.]{0,39}$/;
const finite = value => Number.isFinite(value);
const numbers = (value, allowNull = false) => Array.isArray(value) && value.length === 2
  && value.every(v => finite(v) || (allowNull && v === null));
const text = (value, max = 60) => typeof value === 'string' && value.length > 0 && value.length <= max;
const pct = value => finite(value) && value >= 0 && value <= 100;
const logo = value => (typeof value === 'string' && (/^https:\/\/g\.espncdn\.com\//.test(value) || /^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(value)))
  ? value : null;
const player = p => finite(p?.id) && text(p.name) && (p.points === null || finite(p.points));

function day(value) {
  if (typeof value?.date !== 'string' || !['final', 'live', 'projected'].includes(value.state)) return false;
  const open = value.state === 'final';
  const players = value.players == null || (value.state !== 'projected' && Array.isArray(value.players)
    && value.players.length === 2 && value.players.every(side => Array.isArray(side) && side.every(player)));
  return (value.actual === null || numbers(value.actual, true)) && numbers(value.expected, open) && numbers(value.games, open) && players;
}

function matchup(value, teams) {
  const home = teams.get(value?.home), away = teams.get(value?.away);
  if (!home || !away) return null;
  const base = { home, away, key: `${home.id}-${away.id}` };
  const ok = !value.unavailable && numbers(value.scores) && numbers(value.projected_totals) && pct(value.chance)
    && Array.isArray(value.days) && value.days.every(day)
    && value.days.every((d, i) => i === 0 || d.date > value.days[i - 1].date)
    && (value.odds_history ?? []).every(point => typeof point?.date === 'string' && pct(point.chance));
  return ok ? { ...value, ...base, odds_history: value.odds_history ?? [] } : { ...base, unavailable: true };
}

function season(value, teams) {
  if (!value || typeof value !== 'object' || !value.modes) return null;
  const modes = {};
  for (const mode of MODES) {
    const rows = value.modes[mode];
    if (!Array.isArray(rows)) continue;
    const clean = rows.filter(row => teams.has(row?.team) && pct(row.playoff_pct) && pct(row.title_pct)
      && Array.isArray(row.place_pct) && row.place_pct.length === teams.size && row.place_pct.every(pct))
      .map(row => ({ ...row, team: teams.get(row.team) }));
    if (clean.length === teams.size) modes[mode] = clean;
  }
  if (!Object.keys(modes).length) return null;
  return { modes, history: value.history || {}, playoffTeams: Number.isInteger(value.playoff_teams) ? value.playoff_teams : 4,
    weeksRemaining: value.weeks_remaining, trials: value.trials, formActive: value.form_active === true };
}

// Validates public-v1 or public-v2 into one renderable shape; malformed matchups become "not available".
export function cleanSnapshot(data) {
  if (!['public-v1', 'public-v2'].includes(data?.version) || !Array.isArray(data.matchups) || typeof data.generated_at !== 'string'
    || !Number.isInteger(data.matchup?.id) || typeof data.matchup?.ends !== 'string') return null;
  let teams, raw = data.matchups;
  if (data.version === 'public-v2') {
    if (!Array.isArray(data.teams)) return null;
    teams = new Map(data.teams.filter(t => Number.isInteger(t?.id) && text(t.name))
      .map(t => [t.id, { id: t.id, name: t.name, abbrev: typeof t.abbrev === 'string' ? t.abbrev : '', logo: logo(t.logo),
        manager: typeof t.manager === 'string' && MANAGER.test(t.manager) ? t.manager : null }]));
  } else {
    // v1 named teams inline; give them synthetic ids so both versions render the same way.
    teams = new Map();
    raw = raw.map(m => {
      const ids = [m?.home, m?.away].map(t => {
        if (!text(t?.name)) return null;
        const id = teams.size + 1;
        teams.set(id, { id, name: t.name, abbrev: '', logo: null, manager: null });
        return id;
      });
      return { ...m, home: ids[0], away: ids[1] };
    });
  }
  return {
    // Only v2 carries real ESPN team ids, which is what Dice links are keyed by.
    linkable: data.version === 'public-v2',
    generatedAt: data.generated_at, matchup: data.matchup, year: Number.isInteger(data.season_year) ? data.season_year : null, label: typeof data.label === 'string' ? data.label : '',
    teams, matchups: raw.map(m => matchup(m, teams)).filter(Boolean), season: season(data.season, teams),
  };
}

async function read(url, signal) {
  const timeout = AbortSignal.timeout(TIMEOUT_MS);
  const response = await fetch(url, { signal: signal ? AbortSignal.any([signal, timeout]) : timeout });
  if (response.status === 404) return null;
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return cleanSnapshot(await response.json());
}

// Cozy API first; the interim host only when the API has nothing to serve.
export async function loadSnapshot(apiUrl, signal) {
  let failed = false;
  const urls = apiUrl ? [`${apiUrl}/espn/public/predictions/latest`, FALLBACK_URL] : [FALLBACK_URL];
  for (const url of urls) {
    try {
      const data = await read(url, signal);
      if (data) return data;
    } catch (error) {
      if (signal?.aborted) throw error;
      failed = true;
    }
  }
  if (failed) throw new Error('Predictions unavailable');
  return null;
}
