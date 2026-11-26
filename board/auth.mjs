import { createHash } from 'node:crypto';
import { createClient } from '@supabase/supabase-js';

export function createAuth({ origin, supabaseUrl, supabaseKey, commonsApi, members, agentKeys }) {
    const secure = origin.startsWith('https:');
    const prefix = secure ? '__Host-cc-board-' : 'cc-board-';
    const sessionNames = ['access', 'refresh'];

    function cookie(name, value, maxAge) {
        return `${prefix}${name}=${encodeURIComponent(value)}; Path=/; Max-Age=${maxAge}; HttpOnly; SameSite=Lax${secure ? '; Secure' : ''}`;
    }

    function read(request, name) {
        const key = `${prefix}${name}=`;
        const entry = request.headers.get('cookie')?.split(';').map(part => part.trim()).find(part => part.startsWith(key));
        try {
            return entry ? decodeURIComponent(entry.slice(key.length)) : '';
        } catch {
            return '';
        }
    }

    function client(auth = {}) {
        return createClient(supabaseUrl, supabaseKey, {
            auth: { autoRefreshToken: false, detectSessionInUrl: false, persistSession: false, ...auth },
            global: { fetch: (input, init) => fetch(input, { ...init, signal: AbortSignal.timeout(5000), redirect: 'error' }) },
        }).auth;
    }

    function pkceClient(verifier = '') {
        const storage = new Map([['board-auth-code-verifier', verifier]]);
        const auth = client({
            flowType: 'pkce',
            persistSession: true,
            storageKey: 'board-auth',
            storage: {
                getItem: key => storage.get(key) ?? null,
                setItem: (key, value) => storage.set(key, value),
                removeItem: key => storage.delete(key),
            },
        });
        return { auth, storage };
    }

    function sessionCookies(session) {
        return [
            // Keep the expired access token briefly so refresh happens only once it is needed.
            cookie('access', session.access_token, session.expires_in + 60),
            cookie('refresh', session.refresh_token, 7 * 24 * 3600),
        ];
    }

    function localPath(value) {
        if (typeof value !== 'string' || value.length > 1500) return '/';
        const parsed = URL.parse(value, origin);
        return parsed?.origin === origin ? parsed.href : '/';
    }

    function redirect(location, cookies = []) {
        const headers = new Headers({ location });
        for (const value of cookies) headers.append('set-cookie', value);
        return new Response(null, { status: 303, headers });
    }

    async function identity(token) {
        const { data: { user }, error } = await client().getUser(token);
        if (error) {
            if ([400, 401, 403, 422].includes(error.status)) return { status: 401 };
            throw error;
        }
        if (!user || user.is_anonymous || !user.email || !user.email_confirmed_at) return { status: 403 };

        const email = user.email.toLowerCase();
        if (!members.has(email)) {
            const response = await fetch(`${commonsApi}/admin/session`, {
                headers: { authorization: `Bearer ${token}` },
                redirect: 'error',
                signal: AbortSignal.timeout(5000),
            });
            await response.body?.cancel();
            if ([401, 403].includes(response.status)) return { status: 403 };
            if (!response.ok) throw new Error('Commons access check failed');
        }
        const handle = email.split('@')[0].replace(/[^a-z0-9._-]/g, '-').slice(0, 48) || 'member';
        const expiresAt = new Date(JSON.parse(Buffer.from(token.split('.')[1], 'base64url')).exp * 1000);
        return { status: 200, principal: { id: `commons:user:${user.id}`, kind: 'person', handle, expiresAt } };
    }

    // Several inspector requests can arrive together when a session expires.
    // Share that refresh and its rotated cookies for this burst of requests.
    const refreshing = new Map();
    function refresh(token) {
        if (!refreshing.has(token)) {
            const pending = client().refreshSession({ refresh_token: token });
            refreshing.set(token, pending);
            setTimeout(() => refreshing.delete(token), 5000).unref();
        }
        return refreshing.get(token);
    }

    return {
        async begin(request) {
            const { auth, storage } = pkceClient();
            const { data, error } = await auth.signInWithOAuth({
                provider: 'google',
                options: { redirectTo: `${origin}/auth/callback`, skipBrowserRedirect: true },
            });
            const verifier = storage.get('board-auth-code-verifier');
            if (error || !data.url || !verifier) throw new Error('Google sign-in is unavailable');
            const next = localPath(new URL(request.url).searchParams.get('next'));
            return redirect(data.url, [cookie('verifier', verifier, 600), cookie('next', next, 600)]);
        },

        async callback(request) {
            const verifier = read(request, 'verifier');
            const code = new URL(request.url).searchParams.get('code');
            const clear = ['verifier', 'next'].map(name => cookie(name, '', 0));
            if (!code || !verifier) return redirect('/auth/sign-in?error=sign-in', clear);
            const { auth } = pkceClient(verifier);
            const { data: { session }, error } = await auth.exchangeCodeForSession(code);
            if (error || !session) return redirect('/auth/sign-in?error=sign-in', clear);
            const result = await identity(session.access_token);
            if (result.status !== 200) return redirect('/auth/sign-in?error=access', clear);
            return redirect(localPath(read(request, 'next')), [...clear, ...sessionCookies(session)]);
        },

        async browser(request) {
            const access = read(request, 'access');
            if (access) {
                const result = await identity(access);
                if (result.status !== 401) return result;
            }
            const token = read(request, 'refresh');
            if (!token) return { status: 401 };
            const { data: { session }, error } = await refresh(token);
            if (error && ![400, 401, 403, 422].includes(error.status)) throw error;
            if (!session) return { status: 401 };
            const result = await identity(session.access_token);
            return { ...result, cookies: result.status === 200 ? sessionCookies(session) : [] };
        },

        async api(request) {
            const token = /^Bearer ([\w.-]+)$/i.exec(request.headers.get('authorization') ?? '')?.[1];
            if (!token) return { status: 401 };
            if (!token.startsWith('ccb_')) return identity(token);
            const hash = createHash('sha256').update(token).digest('hex');
            const handle = agentKeys.get(hash);
            if (!handle) return { status: 401 };
            return { status: 200, agent: handle, principal: { id: `commons:agent:${handle}`, kind: 'person', handle } };
        },

        async signOut(request) {
            const access = read(request, 'access');
            if (access) await client().admin.signOut(access, 'local').catch(() => {});
            return redirect('/', sessionNames.map(name => cookie(name, '', 0)));
        },
    };
}
