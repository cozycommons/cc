// Where "back" goes when there is no earlier in-app page to return to (a page
// opened from a shared link or a new tab): the page's parent in Dice.
const PARENTS = [
  [/^\/dice\/game\/([^/]+)\/edit$/, (id) => `/dice/game/${id}`],
  [/^\/dice\/tournament\/([^/]+)\/(virtual|edit)$/, (id) => `/dice/tournament/${id}`],
  [/^\/dice\/tournament\/[^/]+$/, () => '/dice/tournaments'],
  [/^\/dice\/live\/[^/]+$/, () => '/dice/live'],
  [/^\/dice\/stats\/duos\/[^/]+$/, () => '/dice/stats?view=duos'],
  [/^\/dice\/stats\/streaks\/[^/]+$/, () => '/dice/stats?view=streaks'],
  [/^\/dice\/leaderboard\/[^/]+$/, () => '/dice/stats'],
  [/^\/dice\/elo-explained$/, () => '/dice/leaderboard/elo'],
  [/^\/dice\/stats$/, (_, search) => (new URLSearchParams(search).get('view') ? '/dice/stats' : '/dice')],
];

export function diceParentPath(pathname, search = '') {
  for (const [pattern, parent] of PARENTS) {
    const match = pathname.match(pattern);
    if (match) return parent(match[1], search);
  }
  return '/dice';
}
