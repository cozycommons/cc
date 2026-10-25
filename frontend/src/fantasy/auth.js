import { resolveRuntimeServiceUrl } from '../runtimeConfig.js';

// This is only a loading hint. Supabase and the API still validate the session.
export function hasAuthHint(configuredUrl = import.meta.env.VITE_SUPABASE_URL) {
  const markers = ['code', 'access_token', 'error', 'error_code', 'error_description'];
  const query = new URLSearchParams(window.location.search);
  const hash = new URLSearchParams(window.location.hash.slice(1));
  if (markers.some(key => query.has(key) || hash.has(key))) return true;
  try {
    const url = new URL(resolveRuntimeServiceUrl(configuredUrl));
    // Match supabase-js's default storage key, including custom/local hosts.
    return !!window.localStorage.getItem(`sb-${url.hostname.split('.')[0]}-auth-token`);
  } catch {
    // A blocked store or missing configuration is not evidence of a session.
    return false;
  }
}

let loaded = null;
const observers = new Set();
async function loadAuth() {
  loaded ||= import('../supabase');
  const module = await loaded;
  for (const start of observers) start(module.auth);
  return module.auth;
}

export const auth = {
  async getSession() {
    if (!loaded && !hasAuthHint()) return null;
    return (await loadAuth()).getSession();
  },
  async signInWithGoogle(redirectTo) {
    return (await loadAuth()).signInWithGoogle(redirectTo);
  },
  async onAuthStateChange(callback) {
    let subscription;
    let active = true;
    const start = client => {
      if (!active || subscription) return;
      // Reserve the slot before awaiting the shared helper's async subscription.
      subscription = { unsubscribe() {} };
      Promise.resolve().then(() => client.onAuthStateChange(callback)).then(result => {
        subscription = result.data.subscription;
        if (!active) subscription.unsubscribe();
      }).catch(() => { subscription = null; });
    };
    const check = () => {
      if (loaded || hasAuthHint()) loadAuth().catch(() => {});
    };
    observers.add(start);
    window.addEventListener('storage', check);
    check();
    return { data: { subscription: { unsubscribe() {
      active = false;
      observers.delete(start);
      window.removeEventListener('storage', check);
      subscription?.unsubscribe();
    } } } };
  },
};
