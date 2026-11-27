import { AsyncLocalStorage } from 'node:async_hooks';
import { readFile } from 'node:fs/promises';
import { createServer } from 'node:http';
import { join } from 'node:path';
import { Readable } from 'node:stream';
import { pipeline } from 'node:stream/promises';
import { fileURLToPath, pathToFileURL } from 'node:url';
import { board } from '@vercel/board';
import { local } from '@vercel/board/backend-local';
import { createAuth } from './auth.mjs';

const API = '/api/board';
const BROWSER_API = '/board';
const WEB_DIR = fileURLToPath(new URL('../frontend/dist-chat/', import.meta.url));
const PAGE_POLICY = "default-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'self'; img-src 'self' https: data:; frame-ancestors 'none'; base-uri 'none'; form-action 'self'";
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

export async function createBoardService(config) {
    const { origin, dataDir, webDir = WEB_DIR } = config;
    const page = await readFile(join(webDir, 'chat.html'));
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

    async function serveBoard(request, url, authenticated, fromPage) {
        if (authenticated.status !== 200) return requestError(authenticated.status);

        const path = fromPage ? url.pathname.slice(BROWSER_API.length) || '/' : url.pathname.slice(API.length) || '/';
        const decoded = decodeURIComponent(path);
        if (decoded.includes('\\') || decoded.startsWith('//') || decoded.split('/').some(segment => segment === '..' || segment === '.')) {
            return failure(400, 'bad_path', 'Invalid Board path.');
        }
        if (request.method !== 'GET' && (under(decoded, '/watchers') || under(decoded, '/webhooks') || decoded === '/wake')) {
            return failure(403, 'forbidden', 'External integrations are disabled.');
        }

        const headers = new Headers(request.headers);
        for (const name of ['authorization', 'cookie', 'x-chat-request']) headers.delete(name);
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
        if (under(path, BROWSER_API)) {
            const site = request.headers.get('sec-fetch-site');
            if (request.headers.get('x-chat-request') !== '1' || (site && site !== 'same-origin')
                || (!['GET', 'HEAD'].includes(method) && !sameOrigin)) return requestError(403);
            return serveBoard(request, url, await auth.browser(request), true);
        }
        if (path === '/auth/sign-out' && method === 'POST') {
            return sameOrigin ? auth.signOut(request) : requestError(403);
        }
        if (method !== 'GET') return failure(405, 'method_not_allowed', 'Method not allowed.');
        if (path === '/auth/google') return auth.begin(request);
        if (path === '/auth/callback') return auth.callback(request);
        if (path === '/auth/sign-in') return frontPage();
        if (under(path, '/chat-assets')) {
            const asset = /^\/chat-assets\/([a-zA-Z0-9_-]+\.(js|css))$/.exec(path);
            if (!asset) return failure(404, 'not_found', 'Asset not found.');
            const [, name, kind] = asset;
            const data = await readFile(join(webDir, 'chat-assets', name)).catch(error => {
                if (error.code === 'ENOENT') return null;
                throw error;
            });
            if (!data) return failure(404, 'not_found', 'Asset not found.');
            return new Response(data, { headers: {
                'content-type': kind === 'css' ? 'text/css; charset=utf-8' : 'text/javascript; charset=utf-8',
                'cache-control': 'public, max-age=31536000, immutable',
            } });
        }
        if (under(path, '/auth') || under(path, '/api')) return failure(404, 'not_found', 'Page not found.');

        const session = await auth.browser(request);
        if (session.status !== 200) {
            const next = new URL('/auth/sign-in', origin);
            next.searchParams.set('next', path + url.search);
            if (session.status === 403) next.searchParams.set('error', 'access');
            return Response.redirect(next, 303);
        }
        return frontPage(session.cookies);
    }

    function frontPage(cookies = []) {
        const headers = new Headers({
            'content-type': 'text/html; charset=utf-8',
            'content-security-policy': PAGE_POLICY,
        });
        for (const cookie of cookies) headers.append('set-cookie', cookie);
        return new Response(page, { headers });
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
            if (!new URL(request.url).pathname.startsWith('/chat-assets/') || !response.ok) {
                headers['cache-control'] = 'private, no-store';
            }
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
        webDir: env.BOARD_WEB_DIR || WEB_DIR,
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
