// Interim snapshot host until the Cozy upload route is configured in production.
export const FALLBACK_URL = 'https://gist.githubusercontent.com/homatthew/a417a860db31c1a9e5c13b08338b7a65/raw/fantasy-latest.json';

// Active downloads have no total deadline. Only a missing response or stalled body expires.
const HEADER_TIMEOUT_MS = 30000;
const IDLE_TIMEOUT_MS = 20000;
const MODES = ['projections', 'balanced', 'hot'];
const MANAGER = /^[A-Za-z][A-Za-z '\-.]{0,39}$/;
const finite = value => Number.isFinite(value);
const numbers = (value, allowNull = false) => Array.isArray(value) && value.length === 2
  && value.every(v => finite(v) || (allowNull && v === null));
const text = (value, max = 60) => typeof value === 'string' && value.length > 0 && value.length <= max;
const pct = value => finite(value) && value >= 0 && value <= 100;
const logo = (value, apiUrl) => {
  if (typeof value !== 'string') return null;
  if (/^https:\/\/g\.espncdn\.com\//.test(value) || /^data:image\/png;base64,[A-Za-z0-9+/=]+$/.test(value)) return value;
  if (apiUrl && /^\/espn\/public\/logos\/[a-f0-9]{64}$/.test(value)) {
    return `${apiUrl.replace(/\/$/, '')}${value}`;
  }
  return null;
};
const player = p => finite(p?.id) && text(p.name) && (p.points === null || finite(p.points));

function day(value) {
  if (typeof value?.date !== 'string' || !['final', 'live', 'projected'].includes(value.state)) return false;
  const open = value.state === 'final';
  const players = value.players == null || (value.state !== 'projected' && Array.isArray(value.players)
    && value.players.length === 2 && value.players.every(side => Array.isArray(side) && side.every(player)));
  return (value.actual === null || numbers(value.actual, true)) && numbers(value.expected, open) && numbers(value.games, open) && players;
}

// Daily points are Los Angeles dates; place them at noon there (PST or PDT), whatever the viewer's timezone.
const LA_HOUR = new Intl.DateTimeFormat('en-US', { timeZone: 'America/Los_Angeles', hour: 'numeric', hourCycle: 'h23' });
export function laNoon(date) {
  const pst = Date.parse(`${date}T20:00:00Z`);  // noon PST; one hour later in LA during daylight time
  return Number(LA_HOUR.format(pst)) === 13 ? pst - 3600000 : pst;
}

// Intraday points carry their capture time; a missing or null `at` falls back to the daily anchor.
const oddsHistory = points => points
  .map(point => ({ ...point, time: point.at ? Date.parse(point.at) : laNoon(point.date) }))
  .sort((a, b) => a.time - b.time);

function matchup(value, teams) {
  const home = teams.get(value?.home), away = teams.get(value?.away);
  if (!home || !away) return null;
  const base = { home, away, key: `${home.id}-${away.id}` };
  const ok = !value.unavailable && numbers(value.scores) && numbers(value.projected_totals) && pct(value.chance)
    && Array.isArray(value.days) && value.days.every(day)
    && value.days.every((d, i) => i === 0 || d.date > value.days[i - 1].date)
    && (value.odds_history ?? []).every(point => typeof point?.date === 'string' && pct(point.chance)
      && (point.at == null || Number.isFinite(Date.parse(point.at))));
  return ok ? { ...value, ...base, odds_history: oddsHistory(value.odds_history ?? []) } : { ...base, unavailable: true };
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
export function cleanSnapshot(data, apiUrl) {
  if (!['public-v1', 'public-v2'].includes(data?.version) || !Array.isArray(data.matchups) || typeof data.generated_at !== 'string'
    || !Number.isInteger(data.matchup?.id) || typeof data.matchup?.ends !== 'string') return null;
  let teams, raw = data.matchups;
  if (data.version === 'public-v2') {
    if (!Array.isArray(data.teams)) return null;
    teams = new Map(data.teams.filter(t => Number.isInteger(t?.id) && text(t.name))
      .map(t => [t.id, { id: t.id, name: t.name, abbrev: typeof t.abbrev === 'string' ? t.abbrev : '', logo: logo(t.logo, apiUrl),
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

const cacheKey = apiUrl => `fantasy:last-good:v1:${apiUrl || FALLBACK_URL}`;
const usable = data => data?.matchups.some(match => !match.unavailable);

// Store only validated public payloads; revalidate on read across app releases.
export function cachedSnapshot(apiUrl) {
  try {
    const data = cleanSnapshot(JSON.parse(localStorage.getItem(cacheKey(apiUrl))), apiUrl);
    return usable(data) ? data : null;
  } catch { return null; }
}

function remember(apiUrl, raw) {
  try { localStorage.setItem(cacheKey(apiUrl), JSON.stringify(raw)); } catch { /* Storage may be full or disabled. */ }
}

function progress(data, onProgress, done, extra = {}) {
  if (!onProgress) return;
  const { matchups, ...meta } = data;
  onProgress({ meta: { ...meta, totalMatchups: matchups.length,
    slots: matchups.map(({ key, home, away }) => ({ key, home: home.id, away: away.id })),
    seasonAvailable: !!data.season, ...extra }, matchups, done, error: null });
}

function streamSnapshot(onProgress, apiUrl) {
  let raw, extra, ended = false;
  const seen = new Set();
  const publish = () => {
    const data = cleanSnapshot(raw, apiUrl);
    if (!data) throw new Error('Invalid predictions stream');
    progress(data, onProgress, false, extra);
  };
  return {
    line(text) {
      if (!text.trim()) return;
      const line = JSON.parse(text);
      if (ended) throw new Error('Data after stream completion');
      if (line.type === 'meta' && !raw) {
        if (!Number.isInteger(line.total_matchups) || line.total_matchups < 0
          || !Array.isArray(line.slots) || line.slots.length !== line.total_matchups) throw new Error('Invalid stream metadata');
        raw = { ...line.snapshot, matchups: [] };
        extra = { totalMatchups: line.total_matchups, slots: line.slots, seasonAvailable: line.season_available === true };
      } else if (!raw) throw new Error('Missing stream metadata');
      else if (line.type === 'matchup') {
        const key = `${line.matchup?.home}-${line.matchup?.away}`;
        if (seen.has(key) || !extra.slots.some(slot => slot.key === key)) throw new Error('Invalid stream matchup');
        seen.add(key);
        if (Array.isArray(line.teams)) {
          const teams = new Map(raw.teams.map(team => [team.id, team]));
          line.teams.forEach(team => teams.set(team.id, team));
          raw.teams = [...teams.values()];
        }
        raw.matchups.push(line.matchup);
      } else if (line.type === 'season') raw.season = line.season;
      else if (line.type === 'history') {
        for (const match of line.matchups) {
          const target = raw.matchups.find(row => row.home === match.home && row.away === match.away);
          if (!target) throw new Error('Invalid stream history');
          target.odds_history = match.odds_history;
        }
      } else if (line.type === 'done') {
        if (seen.size !== extra.totalMatchups) throw new Error('Incomplete predictions stream');
        ended = true;
      } else throw new Error('Invalid predictions record');
      publish();
    },
    finish() {
      if (!ended) throw new Error('Incomplete predictions stream');
      return raw;
    },
  };
}

async function read(url, signal, apiUrl, onProgress) {
  for (let attempt = 0; attempt < 2; attempt++) {
    const controller = new AbortController();
    let timer, reader, complete = false;
    const cancel = () => controller.abort(signal.reason);
    if (signal?.aborted) controller.abort(signal.reason);
    else signal?.addEventListener('abort', cancel, { once: true });
    let rejectAbort;
    const aborted = new Promise((_, reject) => { rejectAbort = reject; });
    const onAbort = () => rejectAbort(controller.signal.reason);
    controller.signal.addEventListener('abort', onAbort, { once: true });
    // The first race must also observe a caller that cancelled before this attempt.
    if (controller.signal.aborted) onAbort();
    const wait = promise => Promise.race([promise, aborted]);
    const arm = milliseconds => {
      clearTimeout(timer);
      timer = setTimeout(() => controller.abort(new DOMException('Download stalled', 'TimeoutError')), milliseconds);
    };
    try {
      arm(HEADER_TIMEOUT_MS);
      const response = await wait(fetch(url, { signal: controller.signal,
        ...(apiUrl && url !== FALLBACK_URL && { headers: { Accept: 'application/x-ndjson, application/json' } }) }));
      clearTimeout(timer);
      if (response.status === 404) return null;
      if (!response.ok) throw new Error(`HTTP ${response.status}`);
      arm(IDLE_TIMEOUT_MS);
      let raw;
      if (!response.body?.getReader) raw = await wait(response.json());
      else {
        reader = response.body.getReader();
        const decoder = new TextDecoder();
        const ndjson = response.headers.get('content-type')?.includes('application/x-ndjson');
        const records = ndjson ? streamSnapshot(onProgress, apiUrl) : null;
        let buffer = '';
        const consume = text => {
          buffer += text;
          if (records) {
            let end;
            while ((end = buffer.indexOf('\n')) !== -1) {
              records.line(buffer.slice(0, end));
              buffer = buffer.slice(end + 1);
            }
          }
        };
        while (true) {
          const { value, done } = await wait(reader.read());
          if (done) break;
          if (value.byteLength) {
            arm(IDLE_TIMEOUT_MS);
            consume(decoder.decode(value, { stream: true }));
          }
        }
        consume(decoder.decode());
        if (records) {
          if (buffer.trim()) records.line(buffer);
          raw = records.finish();
        } else raw = JSON.parse(buffer);
      }
      clearTimeout(timer);
      const data = cleanSnapshot(raw, apiUrl);
      if (!usable(data)) return null;
      remember(apiUrl, raw);
      complete = true;
      progress(data, onProgress, true);
      return data;
    } catch (error) {
      if (signal?.aborted || attempt === 1 || error.name !== 'TimeoutError') throw error;
    } finally {
      clearTimeout(timer);
      signal?.removeEventListener('abort', cancel);
      controller.signal.removeEventListener('abort', onAbort);
      if (!complete) controller.abort();
      if (reader) {
        if (!complete) reader.cancel().catch(() => {});
        reader.releaseLock();
      }
    }
  }
}

// Cozy API first; the interim host only when the API has nothing to serve.
export async function loadSnapshot(apiUrl, signal, onProgress) {
  let failed = false, latest;
  const emit = event => { latest = event; onProgress?.(event); };
  const urls = apiUrl ? [`${apiUrl}/espn/public/predictions/latest`, FALLBACK_URL] : [FALLBACK_URL];
  for (const url of urls) {
    try {
      const data = await read(url, signal, apiUrl, emit);
      if (data) return data;
    } catch (error) {
      if (signal?.aborted) throw error;
      failed = true;
    }
  }
  const saved = cachedSnapshot(apiUrl);
  if (saved) { progress(saved, emit, true); return saved; }
  if (failed) {
    const error = new Error('Predictions unavailable');
    onProgress?.({ meta: latest?.meta ?? null, matchups: latest?.matchups ?? [], done: true, error });
    throw error;
  }
  return null;
}
