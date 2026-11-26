import { AsyncLocalStorage } from 'node:async_hooks';
import { createServer } from 'node:http';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { pathToFileURL } from 'node:url';
import { board } from '@vercel/board';
import { local } from '@vercel/board/backend-local';
import { inspector } from '@vercel/board/inspect';
import { createAuth } from './auth.mjs';

const API = '/api/board';
const INSPECTOR = '/board';
const AGENT_SCOPE = '*=read,post,react,label';

function under(path, prefix) {
    return path === prefix || path.startsWith(`${prefix}/`);
}

function failure(status, code, message) {
    return Response.json({ error: { code, message } }, { status });
}

function requestError(status) {
    if (status === 403) return failure(403, 'forbidden', 'This account does not have access to Cozy Chat.');
    return failure(401, 'unauthorized', 'Sign in to Cozy Chat or supply a valid Board API token.');
}

function signIn(url, status = 200) {
    const notice = url.searchParams.get('error');
    const message = notice === 'access' ? 'This account does not have access to Cozy Chat.'
        : notice === 'sign-in' ? 'Sign-in expired. Please try again.' : '';
    const href = '/auth/google?' + new URLSearchParams({ next: url.searchParams.get('next') ?? '/' }).toString();
    return new Response(`<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Sign in · Cozy Chat</title>
<style>
body{margin:0;min-height:100dvh;display:grid;place-items:center;background:#131b19;color:#f0f6f3;font:1rem system-ui,sans-serif}
main{width:min(24rem,calc(100% - 3rem));padding:2rem;box-sizing:border-box;border:1px solid #3f5750;border-radius:16px;background:#1c2824}
h1{margin:0 0 1.5rem;font-size:2rem}p{color:#fad4bc}a{display:inline-block;padding:.7rem 1rem;border-radius:8px;background:#c7efd8;color:#183729;font-weight:650;text-decoration:none}
</style></head><body><main><h1>Cozy Chat</h1>${message ? `<p role="alert">${message}</p>` : ''}
<a href="${href}">Continue with Google</a></main></body></html>`, {
        status,
        headers: {
            'content-type': 'text/html; charset=utf-8',
            'content-security-policy': "default-src 'none'; style-src 'unsafe-inline'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        },
    });
}

export async function createBoardService(config) {
    const { origin, dataDir } = config;
    const auth = createAuth(config);
    const caller = new AsyncLocalStorage();
    const store = local({ dir: dataDir });
    const team = board({
        backend: store,
        basePath: API,
        url: origin + API,
        authenticate: () => caller.getStore() ?? null,
        streamMaxMs: 25000,
    });
    // Fail at startup if the persistent volume is missing or unwritable.
    await team.createChannel('general');
    const inspect = inspector({ board: team, basePath: '' });

    async function serveBoard(request, url, authenticated, fromPage) {
        if (authenticated.status !== 200) return requestError(authenticated.status);

        const path = fromPage ? url.pathname.slice(INSPECTOR.length) || '/' : url.pathname.slice(API.length) || '/';
        const decoded = decodeURIComponent(path);
        if (decoded.includes('\\') || decoded.startsWith('//') || decoded.split('/').some(segment => segment === '..' || segment === '.')) {
            return failure(400, 'bad_path', 'Invalid Board path.');
        }
        if (request.method !== 'GET' && (under(decoded, '/watchers') || under(decoded, '/webhooks') || decoded === '/wake')) {
            return failure(403, 'forbidden', 'External integrations are disabled.');
        }

        const headers = new Headers(request.headers);
        for (const name of ['authorization', 'cookie', 'x-inspect-token']) headers.delete(name);
        if (authenticated.agent) {
            // A dedicated token has one identity and cannot administer the board.
            if (headers.has('x-board-can') && headers.get('x-board-can') !== AGENT_SCOPE) {
                return failure(400, 'invalid_scope', 'Dedicated agent tokens use a fixed Board scope.');
            }
            headers.set('x-board-profile', authenticated.agent);
            headers.set('x-board-can', AGENT_SCOPE);
        }
        const target = new Request(origin + API + path + url.search, {
            method: request.method, headers, body: request.body, duplex: 'half', signal: request.signal,
        });
        const response = await caller.run(authenticated.principal, () => team.fetch(target));
        for (const cookie of authenticated.cookies ?? []) response.headers.append('set-cookie', cookie);
        return response;
    }

    async function route(request) {
        const url = new URL(request.url);
        const { pathname: path } = url;
        const method = request.method;
        if (method === 'GET' && path === '/healthz') return new Response('ok');
        if (request.headers.get('host') !== new URL(origin).host) {
            return failure(421, 'wrong_host', 'Use the Cozy Chat hostname.');
        }
        const sameOrigin = request.headers.get('origin') === origin;
        if (under(path, API)) {
            if (method === 'GET' && [API, API + '/', API + '/openapi.json'].includes(path)) return team.fetch(request);
            return serveBoard(request, url, await auth.api(request), false);
        }
        if (under(path, INSPECTOR)) {
            const site = request.headers.get('sec-fetch-site');
            if (request.headers.get('x-inspect-token') !== 'page' || (site && site !== 'same-origin')
                || (!['GET', 'HEAD'].includes(method) && !sameOrigin)) return requestError(403);
            return serveBoard(request, url, await auth.browser(request), true);
        }
        if (path === '/auth/sign-out' && method === 'POST') {
            return sameOrigin ? auth.signOut(request) : requestError(403);
        }
        if (method !== 'GET') return failure(405, 'method_not_allowed', 'Method not allowed.');
        if (path === '/auth/google') return auth.begin(request);
        if (path === '/auth/callback') return auth.callback(request);
        if (path === '/auth/sign-in') return signIn(url);
        if (path === '/app.js') return inspect(request);
        if (under(path, '/auth') || under(path, '/api')) return failure(404, 'not_found', 'Page not found.');

        const session = await auth.browser(request);
        if (session.status !== 200) {
            const next = new URL('/auth/sign-in', origin);
            next.searchParams.set('next', path + url.search);
            if (session.status === 403) next.searchParams.set('error', 'access');
            return Response.redirect(next, 303);
        }
        const response = await inspect(request);
        const html = (await response.text())
            .replace('<meta name="inspect-named" content="1">', '')
            .replace('<title>board</title>', '<title>Cozy Chat</title>')
            .replace('</head>', `<style>
.shell,.boot{height:calc(100dvh - 42px)}
.cc-board-bar{height:42px;padding:0 14px;display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);font:600 14px system-ui,sans-serif}
.cc-board-bar form{margin:0}.cc-board-bar button{font:inherit;color:inherit;cursor:pointer;background:none;border:1px solid var(--line);border-radius:5px;padding:4px 8px}
</style></head>`)
            .replace('<div id="root">', '<header class="cc-board-bar"><span>Cozy Chat</span><form method="post" action="/auth/sign-out"><button type="submit">Sign out</button></form></header><div id="root">');
        const headers = new Headers(response.headers);
        headers.set('content-security-policy', headers.get('content-security-policy').replace("form-action 'none'", "form-action 'self'"));
        for (const cookie of session.cookies ?? []) headers.append('set-cookie', cookie);
        return new Response(html, { headers });
    }

    const server = createServer(async (incoming, outgoing) => {
        const controller = new AbortController();
        outgoing.once('close', () => controller.abort());
        try {
            if (!incoming.url?.startsWith('/') || incoming.url.startsWith('//') || incoming.url.includes('\\')) {
                outgoing.writeHead(400).end();
                return;
            }
            const method = incoming.method;
            const request = new Request(origin + incoming.url, {
                method, headers: incoming.headers,
                body: ['GET', 'HEAD'].includes(method) ? undefined : Readable.toWeb(incoming),
                duplex: 'half', signal: controller.signal,
            });
            let response;
            try {
                response = await route(request);
            } catch (error) {
                response = error instanceof URIError ? failure(400, 'bad_path', 'Invalid Board path.')
                    : failure(503, 'unavailable', 'Cozy Chat is temporarily unavailable.');
            }
            const headers = Object.fromEntries(response.headers);
            if (response.headers.has('set-cookie')) headers['set-cookie'] = response.headers.getSetCookie();
            // Attachments and Board responses can contain private content.
            headers['cache-control'] = 'private, no-store';
            headers['x-content-type-options'] = 'nosniff';
            headers['referrer-policy'] = 'no-referrer';
            outgoing.writeHead(response.status, headers);
            if (!response.body || method === 'HEAD') outgoing.end();
            else await pipeline(Readable.fromWeb(response.body), outgoing);
        } catch {
            if (!outgoing.headersSent && !outgoing.destroyed) outgoing.writeHead(500).end();
            else outgoing.destroy();
        }
    });
    return { server, closeStore: () => store.close() };
}

function readOrigin(value, name) {
    const url = URL.parse(value);
    if (!url || url.origin !== value || (url.protocol !== 'https:' && !(url.protocol === 'http:' && url.hostname === '127.0.0.1'))) {
        throw new Error(`${name} must be an HTTPS origin or an HTTP loopback origin.`);
    }
    return url.origin;
}

function readConfig() {
    const env = process.env;
    const agentKeys = new Map();
    const agents = new Set();
    for (const item of (env.BOARD_AGENT_KEYS ?? '').split(',').map(value => value.trim()).filter(Boolean)) {
        const [, name, hash] = /^([a-z][a-z0-9-]{0,31}):([a-f0-9]{64})$/.exec(item) ?? [];
        if (!name || agents.has(name) || agentKeys.has(hash)) throw new Error('Invalid BOARD_AGENT_KEYS entry.');
        agentKeys.set(hash, name);
        agents.add(name);
    }
    if (!env.SUPABASE_PUBLISHABLE_KEY) throw new Error('Set SUPABASE_PUBLISHABLE_KEY.');
    return {
        origin: readOrigin(env.BOARD_ORIGIN, 'BOARD_ORIGIN'),
        supabaseUrl: readOrigin(env.SUPABASE_URL, 'SUPABASE_URL'),
        commonsApi: readOrigin(env.COMMONS_API_ORIGIN, 'COMMONS_API_ORIGIN'),
        supabaseKey: env.SUPABASE_PUBLISHABLE_KEY,
        dataDir: env.BOARD_DATA_DIR || '.board',
        members: new Set((env.BOARD_MEMBER_EMAILS ?? '').split(',').map(email => email.trim().toLowerCase()).filter(Boolean)),
        agentKeys,
    };
}

if (import.meta.url === pathToFileURL(process.argv[1]).href) {
    const { server, closeStore } = await createBoardService(readConfig());
    server.listen(Number(process.env.PORT ?? 4100), '0.0.0.0');
    for (const signal of ['SIGTERM', 'SIGINT']) {
        process.once(signal, () => server.close(async () => {
            await closeStore();
        }));
    }
}
