// Run against a local Vite server. Install playwright and axe-core in a temporary
// directory, then set FANTASY_QA_MODULES to its package.json (no app dependencies).
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
import { SNAPSHOT_V2 } from '../src/fantasy/fixture.js';
const require = createRequire(process.env.FANTASY_QA_MODULES || import.meta.url);
const { chromium } = require('playwright');
const axePath = require.resolve('axe-core/axe.min.js');
const origin = process.env.FANTASY_QA_URL || 'http://127.0.0.1:8080';
const output = process.env.FANTASY_QA_OUTPUT || '/tmp/fantasy-motion-evidence';
await mkdir(output, { recursive: true });
const browser = await chromium.launch();
const results = [];
try {
  for (const width of [390, 1280]) for (const colorScheme of ['light', 'dark']) {
    const context = await browser.newContext({ viewport: { width, height: 844 }, colorScheme });
    const page = await context.newPage();
    let release, fail = false;
    const gate = new Promise(resolve => { release = resolve; });
    const snapshot = structuredClone(SNAPSHOT_V2);
    snapshot.teams.forEach(team => { team.logo = null; });
    snapshot.matchups.filter(m => !m.unavailable).forEach(m => { m.chance = 51; m.days.find(d => d.state !== 'final').state = 'live'; });
    await page.route(/\/espn\/public\/predictions\/latest|fantasy-latest\.json/, async route => {
      await gate;
      await route.fulfill({ status: fail ? 503 : 200, contentType: 'application/json', body: JSON.stringify(snapshot) });
    });
    await page.route(/\/espn\/public\/owners/, route => route.fulfill({ json: [] }));
    await page.route(/espncdn\.com/, route => route.abort());
    await page.addInitScript(() => {
      window.shifts = [];
      new PerformanceObserver(list => { for (const entry of list.getEntries()) if (!entry.hadRecentInput) window.shifts.push({ value: entry.value, sources: entry.sources.map(s => ({ node: s.node?.className, before: s.previousRect.toJSON(), after: s.currentRect.toJSON() })) }); }).observe({ type: 'layout-shift', buffered: true });
      new MutationObserver(() => {
        if (!window.skeletonAt && document.querySelector('.fx-skeleton')) window.skeletonAt = performance.now();
      }).observe(document, { childList: true, subtree: true });
    });
    await page.goto(`${origin}/fantasy`);
    await page.locator('.fx-skeleton').first().waitFor();
    const loadingHeight = await page.locator('.fx-skeleton').first().evaluate(el => el.getBoundingClientRect().height);
    const bounce = await page.locator('.fx-loading-ball').evaluate(async el => {
      const before = getComputedStyle(el).transform;
      await new Promise(resolve => setTimeout(resolve, 220));
      return before !== getComputedStyle(el).transform;
    });
    assert(bounce, 'Basketball must bounce');
    await page.addScriptTag({ path: axePath });
    const contrast = async state => {
      await page.waitForTimeout(900); // Audit settled text after the intentional arrival fade.
      await page.addScriptTag({ path: axePath });
      const audit = await page.evaluate(() => window.axe.run('.fx-page', { runOnly: ['color-contrast'] }));
      assert.deepEqual(audit.violations.map(v => ({ id: v.id, nodes: v.nodes.map(n => ({ target: n.target, summary: n.failureSummary })) })), [], `${width} ${colorScheme} ${state} contrast`);
    };
    await contrast('loading');
    await page.screenshot({ path: `${output}/${width}-${colorScheme}-loading.png`, fullPage: true });
    release();
    await page.locator('.fx-card--link').first().waitFor();
    await page.waitForTimeout(1000);
    const readyHeight = await page.locator('.fx-card--link').first().evaluate(el => el.getBoundingClientRect().height);
    assert.equal(loadingHeight, readyHeight, 'Skeleton and card geometry match');
    await contrast('hub');
    await page.screenshot({ path: `${output}/${width}-${colorScheme}-hub.png`, fullPage: true });
    const metrics = await page.evaluate(() => ({ skeletonAt: window.skeletonAt, htmlAt: performance.getEntriesByType('navigation')[0].responseEnd, cls: window.shifts.reduce((a,b) => a+b.value, 0), shifts: window.shifts }));
    const card = page.locator('.fx-card--link').first();
    await card.click();
    await page.locator('.fx-hero').waitFor();
    await page.waitForTimeout(900);
    await contrast('matchup');
    await page.screenshot({ path: `${output}/${width}-${colorScheme}-matchup.png`, fullPage: true });
    await page.getByRole('link', { name: '← All matchups' }).click();
    await page.locator('.fx-card--link').first().waitFor();
    await page.emulateMedia({ reducedMotion: 'reduce' });
    await page.reload();
    await page.locator('.fx-card--link').first().waitFor();
    await page.waitForTimeout(700);
    assert.equal(await page.locator('.fx-score').first().innerText(), await page.locator('.fx-score').first().getAttribute('aria-label').then(s => s.replace(' points', '')));
    assert.equal(await page.locator('.fx-arrive').first().evaluate(el => getComputedStyle(el).animationName), 'fx-arrive', 'Card arrival remains active under reduced motion');
    if (width === 390) assert.equal(await page.locator('.fx-tab-indicator').first().evaluate(el => getComputedStyle(el).transitionDuration), '0s', 'Reduced motion makes indicator instant');
    assert.equal(await page.locator('.fx-confetti').count(), 0);
    fail = true;
    await page.reload();
    await page.locator('.fx-updated').waitFor();
    assert.equal(await page.locator('.fx-card--link').count() > 0, true);
    await contrast('cached');
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.getByText('Shot clock ran out.').waitFor();
    await contrast('error');
    fail = false;
    await page.getByRole('button', { name: 'Try again' }).click();
    await page.locator('.fx-card--link').first().waitFor();
    results.push({ width, colorScheme, bounce, loadingHeight, readyHeight, ...metrics });
    await context.close();
  }
  await writeFile(`${output}/results.json`, JSON.stringify(results, null, 2));
  console.log(JSON.stringify(results, null, 2));
} finally { await browser.close(); }
