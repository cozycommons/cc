import { useEffect, useRef, useState } from 'react';
import { useSupabase } from '../contexts/SupabaseContext';
import { diceApi } from './api.js';
import { resolveRuntimeServiceUrl } from '../runtimeConfig.js';

export const ADMIN_EMAILS = new Set(['jason.keungg@gmail.com', 'homatt999@gmail.com']);

function isLocalHarnessOrigin(origin) {
  try {
    const url = new URL(origin);
    const port = Number(url.port);
    return (
      url.origin === origin &&
      url.protocol === 'http:' &&
      (url.hostname === 'localhost' || url.hostname === '127.0.0.1') &&
      Number.isInteger(port) &&
      port >= 1024 &&
      port <= 65535
    );
  } catch {
    return false;
  }
}

export function canUseSyntheticDiceAccount({
  dev,
  mode,
  localHarness,
  supabaseUrl,
  codespacesOrigin,
  browserOrigin,
  email,
  password,
}) {
  if (!dev || mode === 'production' || !localHarness || !email || !password) {
    return false;
  }

  const isLoopback = supabaseUrl === 'http://127.0.0.1:54321';
  const isLoopbackBrowser = isLocalHarnessOrigin(browserOrigin);
  const isCodespacesBrowser =
    browserOrigin === codespacesOrigin ||
    browserOrigin === 'http://127.0.0.1:8080' ||
    browserOrigin === 'http://localhost:8080';
  const isCodespaces =
    codespacesOrigin.startsWith('https://') &&
    supabaseUrl === browserOrigin &&
    isCodespacesBrowser;

  return (isLoopback && isLoopbackBrowser) || isCodespaces;
}

function signInWithSyntheticDiceAccount(supabase) {
  const isLocalHarness = import.meta.env.VITE_DICE_LOCAL_HARNESS === 'true';
  const email = import.meta.env.VITE_LOCAL_DICE_EMAIL;
  const password = import.meta.env.VITE_LOCAL_DICE_PASSWORD;
  const supabaseUrl = resolveRuntimeServiceUrl(import.meta.env.VITE_SUPABASE_URL);
  const canUseAccount = canUseSyntheticDiceAccount({
    dev: import.meta.env.DEV,
    mode: import.meta.env.MODE,
    localHarness: isLocalHarness,
    supabaseUrl,
    codespacesOrigin: import.meta.env.VITE_DICE_CODESPACES_ORIGIN || '',
    browserOrigin: window.location.origin,
    email,
    password,
  });
  if (!canUseAccount) return null;
  return supabase.auth.signInWithPassword({ email, password });
}

async function recoverResetSyntheticSession(supabase, session) {
  if (!session?.access_token || import.meta.env.VITE_DICE_LOCAL_HARNESS !== 'true') return null;
  const email = import.meta.env.VITE_LOCAL_DICE_EMAIL;
  const password = import.meta.env.VITE_LOCAL_DICE_PASSWORD;
  const supabaseUrl = resolveRuntimeServiceUrl(import.meta.env.VITE_SUPABASE_URL);
  const safe = canUseSyntheticDiceAccount({
    dev: import.meta.env.DEV,
    mode: import.meta.env.MODE,
    localHarness: true,
    supabaseUrl,
    codespacesOrigin: import.meta.env.VITE_DICE_CODESPACES_ORIGIN || '',
    browserOrigin: window.location.origin,
    email,
    password,
  });
  if (!safe) return null;

  const { error } = await supabase.auth.getUser(session.access_token);
  if (!error) return null;
  const replacement = await signInWithSyntheticDiceAccount(supabase);
  if (replacement?.error) throw replacement.error;
  return replacement?.data?.session || null;
}

// Shares the same Supabase session as the rest of the site (App.jsx's
// Navbar/Landing use the same useSupabase() context) so signing in on the
// homepage keeps you signed in inside /dice, and vice versa.
export function useDiceAuth() {
  const { supabase } = useSupabase();
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);
  const activeToken = useRef(null);

  useEffect(() => {
    if (!supabase) return;
    let cancelled = false;
    let syncVersion = 0;
    let authEventVersion = 0;

    const syncSession = async (session) => {
      if (cancelled) return;
      const version = ++syncVersion;
      activeToken.current = session?.access_token ?? null;
      setLoading(true);
      setUser(session?.user ?? null);
      setToken(session?.access_token ?? null);
      setProfile(null);
      if (session?.access_token) {
        try {
          const p = await diceApi.getMyProfile(session.access_token);
          if (!cancelled && version === syncVersion) {
            setProfile(p);
          }
        } catch (err) {
          console.error('Failed to load dice profile:', err);
        }
      } else {
        setProfile(null);
      }
      if (!cancelled && version === syncVersion) setLoading(false);
    };

    const initialAuthEventVersion = authEventVersion;
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      try {
        const replacement = await recoverResetSyntheticSession(supabase, session);
        if (authEventVersion !== initialAuthEventVersion) return;
        await syncSession(replacement || session);
      } catch (error) {
        console.error('Failed to refresh the synthetic Dice session:', error);
        if (authEventVersion !== initialAuthEventVersion) return;
        await syncSession(session);
      }
    });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      // getSession above owns initial hydration so a stale pre-reset token is
      // validated before any profile requests are made.
      if (event === 'INITIAL_SESSION') return;
      authEventVersion += 1;
      syncSession(session);
    });

    return () => {
      cancelled = true;
      subscription.unsubscribe();
    };
  }, [supabase]);

  const refreshProfile = async () => {
    if (!token) return;
    const requestedToken = token;
    const p = await diceApi.getMyProfile(requestedToken);
    if (activeToken.current !== requestedToken) return undefined;
    setProfile(p);
    return p;
  };

  const isAdmin = ADMIN_EMAILS.has(user?.email?.toLowerCase());

  const signIn = async () => {
    const localSignIn = await signInWithSyntheticDiceAccount(supabase);
    if (localSignIn) {
      if (localSignIn.error) throw localSignIn.error;
      return;
    }
    await supabase.auth.signInWithOAuth({
      provider: 'google',
      options: { redirectTo: `${window.location.origin}${window.location.pathname}` },
    });
  };

  const signOut = async () => {
    await supabase.auth.signOut();
  };

  return {
    user,
    token,
    profile,
    loading,
    isAdmin,
    refreshProfile,
    signIn,
    signOut,
  };
}
