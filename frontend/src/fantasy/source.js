// Interim snapshot host until the Cozy upload route is configured in production.
export const FALLBACK_URL = 'https://gist.githubusercontent.com/homatthew/a417a860db31c1a9e5c13b08338b7a65/raw/fantasy-latest.json';

const finite = value => Number.isFinite(value);
const numbers = (value, allowNull = false) => Array.isArray(value) && value.length === 2
  && value.every(v => finite(v) || (allowNull && v === null));
const team = value => typeof value?.name === 'string' && value.name.length > 0 && value.name.length <= 60;
const day = value => typeof value?.date === 'string' && ['final', 'live', 'projected'].includes(value.state)
  && (value.actual === null || numbers(value.actual, true))
  && numbers(value.expected, value.state === 'final') && numbers(value.games, value.state === 'final');

function matchup(value) {
  if (!team(value?.home) || !team(value?.away)) return null;
  const ok = !value.unavailable && numbers(value.scores) && numbers(value.projected_totals)
    && finite(value.chance) && value.chance >= 0 && value.chance <= 100
    && Array.isArray(value.days) && value.days.every(day)
    && value.days.every((d, i) => i === 0 || d.date > value.days[i - 1].date)
    && (value.odds_history ?? []).every(point => typeof point?.date === 'string' && finite(point.chance));
  return ok ? value : { home: { name: value.home.name }, away: { name: value.away.name }, unavailable: true };
}

// Only renderable public-v1 data passes; malformed matchups become "not available".
export function cleanSnapshot(data) {
  if (data?.version !== 'public-v1' || !Array.isArray(data.matchups) || typeof data.generated_at !== 'string'
    || !Number.isInteger(data.matchup?.id) || typeof data.matchup?.ends !== 'string') return null;
  return { ...data, label: typeof data.label === 'string' ? data.label : '', matchups: data.matchups.map(matchup).filter(Boolean) };
}

const TIMEOUT_MS = 8000;

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
