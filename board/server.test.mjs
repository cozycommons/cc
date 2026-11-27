import assert from 'node:assert/strict';
import { execFile } from 'node:child_process';
import { createHash } from 'node:crypto';
import { mkdir, mkdtemp, rm, writeFile } from 'node:fs/promises';
import { createServer, get } from 'node:http';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { after, before, test } from 'node:test';
import { promisify } from 'node:util';
import { fileURLToPath } from 'node:url';
import { createBoardService } from './server.mjs';

const uuid = '97b6c3d7-a15b-4af2-b982-19d961988fb4';
const jwt = name => `test.${Buffer.from(JSON.stringify({ exp: Math.floor(Date.now() / 1000) + 3600, sub: name })).toString('base64url')}.test`;
const member = jwt('member');
const admin = jwt('admin');
const other = jwt('other');
const expired = 'expired';
const agent = 'ccb_synthetic_agent_token';
let service, server, provider, origin, providerOrigin, dataDir, config, pkceChallenge;
let refreshRequests = 0;

const listen = server => new Promise(resolve => server.listen(0, '127.0.0.1', () => resolve(`http://127.0.0.1:${server.address().port}`)));
const close = server => new Promise(resolve => server.close(resolve));

before(async () => {
    dataDir = await mkdtemp(join(tmpdir(), 'cozy-board-test-'));
    const webDir = join(dataDir, 'web');
    await mkdir(join(webDir, 'chat-assets'), { recursive: true });
    await writeFile(join(webDir, 'chat.html'), '<title>Cozy Chat</title><script src="/chat-assets/chat-test.js"></script>');
    await writeFile(join(webDir, 'chat-assets', 'chat-test.js'), '// test asset');
    provider = createServer(async (req, res) => {
        const url = new URL(req.url, 'http://127.0.0.1');
        const token = req.headers.authorization?.slice(7);
        const reply = (status, body) => res.writeHead(status, { 'content-type': 'application/json' }).end(JSON.stringify(body));
        const user = token => ({ id: token === other ? 'another-user' : uuid, email: token === admin ? 'admin@example.test'
            : token === other ? 'other@example.test' : 'member@example.test', email_confirmed_at: '2026-01-01' });
        const session = { access_token: member, refresh_token: 'refreshed', expires_in: 3600, token_type: 'bearer', user: user(member) };
        if (url.pathname === '/admin/session') return reply(token === admin ? 200 : 403, {});
        if (url.pathname === '/auth/v1/user') {
            return [member, admin, other].includes(token) ? reply(200, user(token)) : reply(401, { message: 'Invalid token' });
        }
        if (url.pathname === '/auth/v1/token') {
            let raw = '';
            for await (const chunk of req) raw += chunk;
            const body = JSON.parse(raw);
            if (url.searchParams.get('grant_type') === 'refresh_token') {
                refreshRequests++;
                await new Promise(resolve => setTimeout(resolve, 20));
                return body.refresh_token === 'refresh-me' ? reply(200, session) : reply(401, { message: 'Invalid token' });
            }
            const challenge = createHash('sha256').update(body.code_verifier).digest('base64url');
            return challenge === pkceChallenge && body.auth_code === 'synthetic-code'
                ? reply(200, session) : reply(401, { message: 'Invalid code' });
        }
        return reply(404, {});
    });
    providerOrigin = await listen(provider);
    // Use a fixed origin selected by the operating system before building the service.
    const reserve = createServer();
    origin = await listen(reserve);
    await close(reserve);
    config = {
        origin, dataDir, webDir, supabaseUrl: providerOrigin, supabaseKey: 'synthetic-key', commonsApi: providerOrigin,
        members: new Set(['member@example.test']),
        agentKeys: new Map([[createHash('sha256').update(agent).digest('hex'), 'codex']]),
    };
    service = await createBoardService(config);
    server = service.server;
    await new Promise(resolve => server.listen(Number(new URL(origin).port), '127.0.0.1', resolve));
});

after(async () => {
    if (server?.listening) await close(server);
    await service?.closeStore();
    if (provider?.listening) await close(provider);
    if (dataDir) await rm(dataDir, { recursive: true, force: true });
});

const fetchBoard = (path, options) => fetch(origin + path, { redirect: 'manual', ...options });
const bearer = token => ({ authorization: `Bearer ${token}` });
const browser = { cookie: `cc-board-access=${member}`, 'x-chat-request': '1' };
const post = (headers, body) => ({ method: 'POST', headers: { ...headers, 'content-type': 'application/json' }, body: JSON.stringify(body) });

test('private board permits only verified members and Commons admins', async () => {
    const anonymous = await fetchBoard('/?thread=42');
    assert.equal(anonymous.status, 303);
    assert.equal(new URL(anonymous.headers.get('location')).searchParams.get('next'), '/?thread=42');
    assert.equal((await fetchBoard('/api/board/openapi.json')).status, 200);
    assert.equal((await fetchBoard('/api/board/me')).status, 401);
    assert.equal((await fetchBoard('/api/board/me', { headers: browser })).status, 401);
    assert.equal((await fetchBoard('/api/board/me', { headers: bearer(other) })).status, 403);
    assert.equal((await fetchBoard('/api/board/me', { headers: bearer(admin) })).status, 200);
    assert.equal((await fetchBoard('/board/me', { headers: bearer(admin) })).status, 403);
    assert.equal((await fetchBoard('/board/me', { headers: { ...browser, 'sec-fetch-site': 'same-site' } })).status, 403);
});

test('Google PKCE preserves a board link and keeps the session in HTTP-only cookies', async () => {
    const begin = await fetchBoard('/auth/google?next=%2F%3Fthread%3D42');
    const provider = new URL(begin.headers.get('location'));
    assert.equal(provider.searchParams.get('provider'), 'google');
    assert.equal(provider.searchParams.get('redirect_to'), origin + '/auth/callback');
    pkceChallenge = provider.searchParams.get('code_challenge');
    assert.ok(pkceChallenge);
    const cookie = begin.headers.getSetCookie().map(value => value.split(';')[0]).join('; ');
    const missing = await fetchBoard('/auth/callback?code=synthetic-code');
    assert.match(missing.headers.get('location'), /error=sign-in/);
    const callback = await fetchBoard('/auth/callback?code=synthetic-code', { headers: { cookie } });
    assert.equal(callback.headers.get('location'), origin + '/?thread=42');
    assert.equal(callback.headers.getSetCookie().filter(value => value.includes('HttpOnly')).length, 4);

    const page = await fetchBoard('/', { headers: browser });
    const html = await page.text();
    assert.equal(page.status, 200);
    assert.match(html, /<title>Cozy Chat/);
    assert.match(page.headers.get('content-security-policy'), /script-src 'self'/);
    assert.equal((await fetchBoard('/chat-assets/chat-test.js')).status, 200);
    assert.equal((await fetchBoard('/chat-assets/missing.js')).status, 404);

    const external = await fetchBoard('/auth/google?next=%2F%09%2Fevil.example');
    const nextCookie = external.headers.getSetCookie().find(value => value.startsWith('cc-board-next='));
    assert.match(nextCookie, /^cc-board-next=%2F;/);

    assert.equal((await fetchBoard('/auth/sign-out', { method: 'POST', headers: browser })).status, 403);
    const logout = await fetchBoard('/auth/sign-out', { method: 'POST', headers: { ...browser, origin } });
    assert.equal(logout.status, 303);
    assert.ok(logout.headers.getSetCookie().every(value => value.includes('Max-Age=0')));
});

test('parallel UI requests share one refresh', async () => {
    const headers = { ...browser, cookie: `cc-board-access=${expired}; cc-board-refresh=refresh-me` };
    const results = await Promise.all([fetchBoard('/board/me', { headers }), fetchBoard('/board/channels', { headers })]);
    for (const result of results) {
        assert.equal(result.status, 200);
        assert.equal(result.headers.getSetCookie().length, 2);
    }
    assert.equal(refreshRequests, 1);
});

test('human posts, agent replies, and native API returns the same thread', async () => {
    const denied = await fetchBoard('/board/messages', post({ ...browser, origin: 'https://evil.example' }, { channel: 'general', text: 'cross-origin' }));
    assert.equal(denied.status, 403);
    const sent = await fetchBoard('/board/messages', post({ ...browser, origin }, { channel: 'general', text: 'Can you take a look?' }));
    assert.equal(sent.status, 201, await sent.clone().text());
    const { message: root } = await sent.json();

    const authenticated = await fetchBoard('/api/board/me', { headers: { ...bearer(agent), 'x-board-profile': 'pretend' } });
    assert.equal(authenticated.status, 200, await authenticated.clone().text());
    const actor = await authenticated.json();
    assert.equal(actor.profile, 'codex');
    assert.match(actor.actor, /^commons:agent:codex\+codex$/);
    assert.equal((await fetchBoard('/api/board/grants', { headers: bearer(agent) })).status, 403);

    const replied = await fetchBoard('/api/board/messages', post(bearer(agent), { re: root.id, text: 'Taking a look.' }));
    assert.equal(replied.status, 201, await replied.clone().text());
    const thread = await fetchBoard(`/board/messages/${root.id}`, { headers: browser });
    assert.equal(thread.status, 200);
    const { message, replies } = await thread.json();
    assert.equal(message.by.principal, `commons:user:${uuid}`);
    assert.equal(message.author.handle, 'member');
    assert.equal(message.author.verified, true);
    assert.equal(replies[0].text, 'Taking a look.');

    const reopened = await createBoardService(config);
    try {
        await listen(reopened.server);
        const port = reopened.server.address().port;
        const loaded = await new Promise((resolve, reject) => {
            get({
                host: '127.0.0.1', port, path: '/api/board/messages/' + root.id,
                headers: { ...bearer(agent), host: new URL(origin).host },
            }, resolve).on('error', reject);
        });
        let body = '';
        for await (const chunk of loaded) body += chunk;
        assert.equal(loaded.statusCode, 200);
        assert.equal(JSON.parse(body).replies[0].text, 'Taking a look.');
    } finally {
        await close(reopened.server);
        await reopened.closeStore();
    }
});

test('the upstream CLI can identify itself and work a task', async () => {
    const cli = fileURLToPath(new URL('./node_modules/@vercel/board/dist/cli.mjs', import.meta.url));
    const run = async (...args) => {
        const { stdout } = await promisify(execFile)(process.execPath, [cli, ...args], {
            env: { ...process.env, XDG_CONFIG_HOME: dataDir, BOARD_URL: origin + '/api/board', BOARD_TOKEN: agent },
            timeout: 5000,
        });
        return stdout;
    };
    assert.match(await run('whoami'), /commons:agent:codex/);
    const task = await run('tasks', 'create', 'general', 'Review the proposal');
    const id = task.trim();
    assert.match(id, /^\d+$/);
    assert.match(await run('tasks', 'claim', id), /yours/);
    assert.match(await run('tasks', 'complete', id, 'Reviewed.'), /completed/);
    assert.match(await run('read', 'general'), /Review the proposal/);
});
