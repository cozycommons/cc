import { test, expect } from '@playwright/test';

const apiOrigin = 'http://localhost:8000';
const adminUser = {
  id: 'u3',
  email: 'jason.keungg@gmail.com',
  user_metadata: {},
};
const expiresAt = Math.floor(Date.now() / 1000) + 3600;
const fakeAccessToken = [
  Buffer.from(JSON.stringify({ alg: 'HS256', typ: 'JWT' })).toString('base64url'),
  Buffer.from(JSON.stringify({ sub: adminUser.id, email: adminUser.email, role: 'authenticated', exp: expiresAt })).toString('base64url'),
  'browser-regression-signature',
].join('.');
const session = {
  access_token: fakeAccessToken,
  refresh_token: 'browser-regression-refresh-token',
  token_type: 'bearer',
  expires_in: 3600,
  expires_at: expiresAt,
  user: adminUser,
};

async function installAdminSession(page) {
  await page.addInitScript(({ value }) => {
    localStorage.setItem('sb-yllwleldhtjyqjgdfrpn-auth-token', JSON.stringify(value));
    localStorage.setItem('sb-127-auth-token', JSON.stringify(value));
  }, { value: session });
}

function profile(id, name) {
  return {
    user_id: id,
    display_name: name,
    avatar_url: null,
    elo_rating: 1500,
    games_played: 0,
    ranked_games_played: 0,
    wins: 0,
    losses: 0,
    ranked_wins: 0,
    ranked_losses: 0,
    normal_wins: 0,
    normal_losses: 0,
    self_sinks: 0,
    sinks: 0,
    hide_from_leaderboard: false,
  };
}

test('Dice home retries a transient games failure and renders the recovered match', async ({ page }) => {
  let gameAttempts = 0;
  await page.route(`${apiOrigin}/dice/**`, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/dice/games') {
      gameAttempts += 1;
      if (gameAttempts === 1) return route.fulfill({ status: 500, body: 'broken pipe' });
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([
        { id: 'game-1', team1_score: 1, team2_score: 4, ranked: false, played_at: '2026-09-03T12:00:00Z', players: [] },
      ]) });
    }
    if (url.pathname === '/dice/tournaments') return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    if (url.pathname.includes('/leaderboard/')) return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    if (url.pathname === '/dice/photos') return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    return route.continue();
  });

  await page.goto('/dice');
  await expect(page.getByText('1 – 4')).toBeVisible();
  await expect(page.getByText('No matches logged yet.')).toHaveCount(0);
  expect(gameAttempts).toBe(2);
});

test('Tournament directory stays reachable from a narrow mobile home', async ({ page }) => {
  await page.route(`${apiOrigin}/dice/**`, (route) => route.fulfill({
    status: 200,
    contentType: 'application/json',
    body: '[]',
  }));
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto('/dice');

  const section = page.getByText('// TOURNAMENTS').locator('..').locator('..');
  await expect(section).toBeVisible();
  if (process.env.DICE_QA_EVIDENCE) await page.screenshot({ path: `${process.env.DICE_QA_EVIDENCE}/home-tournaments-mobile.png`, fullPage: true });
  await section.getByRole('link', { name: 'View all →' }).click();

  await expect(page).toHaveURL(/\/dice\/tournaments$/);
  await expect(page.locator('.jk-display').filter({ hasText: /^Tournaments$/ })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  if (process.env.DICE_QA_EVIDENCE) await page.screenshot({ path: `${process.env.DICE_QA_EVIDENCE}/tournaments-mobile.png`, fullPage: true });
});

test('Dice home gives current streaks player identity and a direct Stats destination', async ({ page }) => {
  const streakGames = [1, 2, 3].map((number) => ({
    id: `streak-${number}`,
    played_at: `2026-09-0${number}T12:00:00Z`,
    winner_team: 1,
    ranked: true,
    players: [{ ...profile('alice', 'Alice A'), team: 1, avatar_url: null }],
  }));
  await page.route(`${apiOrigin}/dice/**`, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/dice/games') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(streakGames) });
    if (url.pathname === '/dice/tournaments' || url.pathname.includes('/leaderboard/') || url.pathname === '/dice/photos') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    }
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dice');
  const streakCard = page.getByRole('link', { name: /Alice A CURRENT STREAK 3/ });
  await expect(streakCard).toBeVisible();
  await expect(streakCard).toHaveAttribute('href', '/dice/stats/streaks/alice');
  const section = page.getByText('// CURRENT WIN STREAKS').locator('..').locator('..');
  await expect(section.getByRole('link', { name: 'View all →' })).toHaveAttribute('href', '/dice/stats?view=streaks');
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  if (process.env.DICE_QA_EVIDENCE) await page.screenshot({ path: `${process.env.DICE_QA_EVIDENCE}/home-streak.png`, fullPage: true });
});

test('Streak detail has a mobile win timeline and player discovery lives in ELO', async ({ page }) => {
  const players = [profile('alice', 'Alice A'), profile('bob', 'Bob B')];
  const streakGames = [1, 2, 3].map((number) => ({
    id: `streak-${number}`,
    played_at: `2026-09-0${number}T12:00:00Z`,
    winner_team: 1,
    team1_score: 11,
    team2_score: number + 5,
    ranked: true,
    players: [{ ...players[0], team: 1 }, { ...players[1], team: 2 }],
  }));
  await page.route(`${apiOrigin}/dice/**`, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/dice/games') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(streakGames) });
    if (url.pathname === '/dice/leaderboard/elo') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([
      { ...players[0], elo_rating: 1600, is_provisional: false },
      { ...players[1], elo_rating: 1500, is_provisional: false },
    ]) });
    return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dice/stats/streaks/alice');
  await expect(page.getByRole('heading', { name: 'Alice A' })).toBeVisible();
  await expect(page.getByText('ACTIVE', { exact: true }).locator('..')).toContainText('3');
  await expect(page.getByText('BEST', { exact: true }).locator('..')).toContainText('3');
  await expect(page.getByText('// CURRENT & BEST RUN')).toBeVisible();
  await expect(page.getByRole('link', { name: /11–6/ })).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  if (process.env.DICE_QA_EVIDENCE) await page.screenshot({ path: `${process.env.DICE_QA_EVIDENCE}/streak-detail.png`, fullPage: true });

  await page.goto('/dice/players');
  await expect(page).toHaveURL(/\/dice\/leaderboard\/elo$/);
  await page.getByRole('textbox', { name: 'Search players' }).fill('Bob');
  await expect(page.getByText('Bob B')).toBeVisible();
  await expect(page.getByText('Alice A')).toHaveCount(0);
  if (process.env.DICE_QA_EVIDENCE) await page.screenshot({ path: `${process.env.DICE_QA_EVIDENCE}/elo-player-search.png`, fullPage: true });
});

test('Dice live result can be deleted from its Home-linked detail page while edits use referee correction', async ({ page }) => {
  await installAdminSession(page);
  await page.route(`${apiOrigin}/dice/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === '/dice/me') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(profile('u3', 'Jason Keung')) });
    if (url.pathname === '/dice/profiles/search') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([profile('u1', 'Andrew S'), profile('u2', 'Aziz Rahman')]) });
    if (url.pathname === '/dice/games/live-game') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
        id: 'live-game', source_live_match_id: 'live-match-1', created_by: 'u3', ranked: false, team1_score: 1, team2_score: 4,
        winner_team: 2, played_at: '2026-09-03T12:00:00Z', players: [
          { user_id: 'u1', display_name: 'Andrew S', team: 1, self_sinks: 0, sinks: 0 },
          { user_id: 'u2', display_name: 'Aziz Rahman', team: 2, self_sinks: 0, sinks: 0 },
        ],
      }) });
    }
    if (request.method() === 'PUT' && url.pathname === '/dice/games/live-game') {
      return route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: {
        code: 'dice_game.live_result_requires_referee_correction',
        message: 'This game came from the live referee. Correct it from the referee view before changing or deleting it.',
      } }) });
    }
    if (request.method() === 'DELETE' && url.pathname === '/dice/games/live-game') {
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ deleted: true }) });
    }
    if (url.pathname === '/dice/games/live-game/comments') return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    return route.continue();
  });

  await page.goto('/dice/game/live-game/edit');
  await expect(page.getByRole('button', { name: 'Save Changes' })).toBeVisible();
  await page.goto('/dice/game/live-game');
  await expect(page.getByRole('button', { name: 'Correct in referee' })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Delete' })).toBeVisible();
  page.once('dialog', (dialog) => dialog.accept());
  await page.getByRole('button', { name: 'Delete' }).click();
  await expect(page).toHaveURL(/\/dice$/);
});

test('referee attributes a table catch and the same recorded stats survive on game detail', async ({ page }) => {
  await installAdminSession(page);
  let commandBody;
  const players = [
    { user_id: 'alice', display_name: 'Alice A', team: 1, avatar_url: null, self_sinks: 0, sinks: 0 },
    { user_id: 'bea', display_name: 'Bea B', team: 1, avatar_url: null, self_sinks: 0, sinks: 0 },
    { user_id: 'cam', display_name: 'Cam C', team: 2, avatar_url: null, self_sinks: 0, sinks: 0 },
    { user_id: 'dev', display_name: 'Dev D', team: 2, avatar_url: null, self_sinks: 0, sinks: 0 },
  ];
  const liveGame = {
    id: 'stats-live', team_order: ['blue', 'clay'], created_at: '2026-09-05T12:00:00Z',
    teams: { blue: ['alice', 'bea'], clay: ['cam', 'dev'] }, score: [1, 1], status: 'active', version: 7,
    detail_coverage: 'partial', player_names: { alice: 'Alice A', bea: 'Bea B', cam: 'Cam C', dev: 'Dev D' },
    player_avatars: {}, referees: [{ user_id: 'u3', left_at: null }], events: [],
    projection: {
      score: [1, 1], status: 'active', coverage: 'partial', stats: { miss: 2, caught: 1, point: 1 },
      player_stats: {
        alice: { outcomes: { miss: 1, caught: 1 } }, bea: { outcomes: { point: 1 } },
        cam: { outcomes: { miss: 1 }, table_catches: 1 }, dev: { outcomes: {} },
      },
    },
  };
  await page.route(`${apiOrigin}/dice/**`, async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    if (url.pathname === '/dice/me') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(profile('u3', 'Jason Keung')) });
    if (url.pathname === '/dice/live/games/stats-live' && request.method() === 'GET') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(liveGame) });
    if (url.pathname === '/dice/live/games/stats-live/commands') {
      commandBody = request.postDataJSON();
      return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ accepted_version: 8, projection: liveGame.projection }) });
    }
    if (url.pathname === '/dice/games/stats-result') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({
      id: 'stats-result', source_live_match_id: 'stats-live', created_by: 'u3', ranked: true,
      team1_score: 5, team2_score: 3, winner_team: 1, played_at: '2026-09-05T12:10:00Z', created_at: '2026-09-05T12:00:00Z', players,
      recorded_stats: { coverage: 'partial', observations: 4, outcomes: liveGame.projection.stats, players: liveGame.projection.player_stats },
    }) });
    if (url.pathname.endsWith('/comments')) return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dice/live/stats-live');
  await page.getByRole('button', { name: 'Table hit' }).click();
  await page.getByRole('button', { name: 'WHO CAUGHT IT?: Cam C' }).click();
  await expect.poll(() => commandBody).toMatchObject({ kind: 'record_throw', thrower_id: 'alice', outcome: 'caught', catcher_id: 'cam' });
  await page.getByLabel('Live game view').getByRole('button', { name: 'Stats' }).click();
  await expect(page.getByRole('region', { name: 'Player game stats' })).toBeVisible();
  await expect(page.getByLabel('1 catch')).toBeVisible();
  await expect(page.getByText('Missing plays are excluded, not counted as misses.')).toBeVisible();

  await page.setViewportSize({ width: 320, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.goto('/dice/game/stats-result');
  await expect(page.getByRole('region', { name: 'Player game stats' })).toBeVisible();
  await expect(page.getByLabel('1 catch')).toBeVisible();
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
});

test('Stats has one canonical path to ranked and provisional detail with reliable back navigation', async ({ page }) => {
  await installAdminSession(page);
  const qualified = {
    duo_id: '5:alice3:bea', members: [profile('alice', 'Alice A'), profile('bea', 'Bea B')],
    elo: 1582, wins: 4, losses: 1, games: 5, win_rate: 0.8, rank: 1, homepage_eligible: true,
  };
  const tiedQualified = {
    duo_id: '3:cam3:dev', members: [profile('cam', 'Cam C'), profile('dev', 'Dev D')],
    elo: 1601, wins: 3, losses: 0, games: 3, win_rate: 1, rank: 1, homepage_eligible: true,
  };
  const thirdQualified = {
    duo_id: '5:alice3:dev', members: [profile('alice', 'Alice A'), profile('dev', 'Dev D')],
    elo: 1510, wins: 3, losses: 2, games: 5, win_rate: 0.6, rank: 3, homepage_eligible: true,
  };
  const provisional = {
    duo_id: '3:bea3:cam', members: [profile('bea', 'Bea B'), profile('cam', 'Cam C')],
    elo: 1540, wins: 2, losses: 0, games: 2, win_rate: 1, rank: null, homepage_eligible: false,
  };
  const statPlayers = [
    { ...profile('alice', 'Alice A'), team: 1 }, { ...profile('bea', 'Bea B'), team: 1 },
    { ...profile('cam', 'Cam C'), team: 2 }, { ...profile('dev', 'Dev D'), team: 2 },
  ];
  const statGames = [1, 2].map((number) => ({
    id: `recorded-${number}`, winner_team: 1, played_at: `2026-09-0${number}T12:00:00Z`, players: statPlayers,
    recorded_stats: {
      schema_version: 'dice-recorded-stats/v1', coverage: number === 1 ? 'complete' : 'partial', observations: 8,
      players: {
        alice: { outcomes: { point: 2, caught: 2, miss: 1, fifa: 1 }, fifa_goals: 1, fifa_kicks: 1 },
        bea: { outcomes: { caught: 1, miss: 1 }, table_catches: 2 }, cam: { outcomes: {} }, dev: { outcomes: {} },
      },
    },
  }));
  await page.route(`${apiOrigin}/dice/**`, async (route) => {
    const url = new URL(route.request().url());
    if (url.pathname === '/dice/me') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(profile('u3', 'Jason Keung')) });
    if (url.pathname === '/dice/games') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify(statGames) });
    if (url.pathname === '/dice/stats/duos') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify({ ranked: [qualified, tiedQualified, thirdQualified], to_watch: [provisional] }) });
    if (url.pathname === '/dice/leaderboard/elo') return route.fulfill({ status: 200, contentType: 'application/json', body: JSON.stringify([
      { ...profile('alice', 'Alice A'), elo_rating: 1600, is_provisional: false },
      { ...profile('bea', 'Bea B'), elo_rating: 1600, is_provisional: false },
    ]) });
    if (url.pathname.includes('/leaderboard/')) return route.fulfill({ status: 200, contentType: 'application/json', body: '[]' });
    return route.fulfill({ status: 404, contentType: 'application/json', body: '{}' });
  });

  for (const width of [390, 320]) {
    await page.setViewportSize({ width, height: 844 });
    await page.goto('/dice/stats?view=duos');
    await expect(page.getByLabel('2 duos tied for first')).toBeVisible();
    await expect(page.getByText('Alice A + Bea B')).toBeVisible();
    await expect(page.getByText('Cam C + Dev D')).toBeVisible();
    await expect(page.getByRole('link').filter({ hasText: 'Alice A + Dev D' }).getByText('3', { exact: true })).toBeVisible();
    await expect(page.getByText('// Provisional duos')).toBeVisible();
    await expect(page.getByText('PROVISIONAL', { exact: true })).toBeVisible();
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
    if (width === 390 && process.env.DICE_QA_EVIDENCE) {
      await page.screenshot({ path: `${process.env.DICE_QA_EVIDENCE}/duos.png`, fullPage: true });
    }
  }

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/dice/stats');
  await expect(page.getByLabel('2 players tied for first')).toBeVisible();
  await expect(page.getByLabel('Recorded player attribution')).toBeVisible();
  await expect(page.getByText('16', { exact: true })).toBeVisible();
  if (process.env.DICE_QA_EVIDENCE) {
    await page.screenshot({ path: `${process.env.DICE_QA_EVIDENCE}/players.png`, fullPage: true });
  }
  await page.setViewportSize({ width: 320, height: 844 });
  await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= document.documentElement.clientWidth)).toBe(true);
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole('tab', { name: 'streaks' }).click();
  await expect(page.getByRole('region', { name: 'Win streaks' })).toBeVisible();
  await expect(page.getByLabel('Longest win streaks')).toBeVisible();
  if (process.env.DICE_QA_EVIDENCE) {
    await page.waitForTimeout(250);
    await page.screenshot({ path: `${process.env.DICE_QA_EVIDENCE}/streaks.png`, fullPage: true });
  }

  for (const path of ['elo', 'sinks', 'self-sinks']) {
    await page.goto(`/dice/leaderboard/${path}`);
    const back = page.getByRole('link', { name: '← Player stats' });
    await expect(back).toBeVisible();
    await back.click();
    await expect(page).toHaveURL(/\/dice\/stats$/);
  }
});
