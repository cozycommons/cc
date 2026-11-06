import { useSyncExternalStore } from 'react';

// The signed-in Cozy Commons identity, shared by every project's header.
//
// One store per page: it loads the Supabase client after first paint (so
// signed-out pages such as the home page never wait on it), follows auth
// changes, and reads the Commons profile from GET /account. Until that answers,
// the header shows the Google name and photo from the session, so a signed-in
// user always sees their own avatar. Any failure leaves the page usable and
// signed out rather than throwing into a product's render.

const SIGNED_OUT = { status: 'signed-out', user: null, profile: null };
let state = { status: 'loading', user: null, profile: null };
const listeners = new Set();
let started = false;
let client = null;
let generation = 0;

function set(next) {
  state = next;
  listeners.forEach((listener) => listener());
}

export function sessionProfile(user) {
  const metadata = user?.user_metadata || {};
  return {
    user_id: user?.id,
    email: user?.email,
    display_name: metadata.full_name || metadata.name || user?.email?.split('@')[0] || 'You',
    avatar_url: metadata.avatar_url || metadata.picture || null,
  };
}

async function apiBase() {
  const { getUrl } = await import('../api.js');
  return getUrl();
}

export async function accountRequest(path, { method = 'GET', body } = {}) {
  const { data } = await client.auth.getSession();
  const token = data?.session?.access_token;
  if (!token) throw new Error('Sign in to manage your account.');
  const response = await fetch(`${await apiBase()}/account${path}`, {
    method,
    headers: { Authorization: `Bearer ${token}`, ...(body ? { 'Content-Type': 'application/json' } : {}) },
    body: body ? JSON.stringify(body) : undefined,
  });
  if (response.status === 204) return null;
  const payload = await response.json().catch(() => ({}));
  if (!response.ok) throw new Error(typeof payload.detail === 'string' ? payload.detail : 'Something went wrong. Try again.');
  return payload;
}

async function loadProfile(user) {
  const current = ++generation;
  try {
    const profile = await accountRequest('');
    if (current === generation && state.user?.id === user.id) set({ ...state, profile });
  } catch {
    // Keep the session's Google identity; the next auth change or refresh retries.
  }
}

function accept(session) {
  const user = session?.user ?? null;
  // Anonymous Supabase sessions (Dice guests) have no Commons account.
  if (!user || user.is_anonymous) { generation += 1; set(SIGNED_OUT); return; }
  const sameUser = state.user?.id === user.id;
  set({ status: 'signed-in', user, profile: sameUser && state.profile ? state.profile : sessionProfile(user) });
  if (!sameUser) loadProfile(user);
}

async function start() {
  try {
    const { getClient } = await import('../supabase.js');
    client = getClient();
    const { data } = await client.auth.getSession();
    accept(data?.session);
    client.auth.onAuthStateChange((_event, session) => accept(session));
  } catch {
    set(SIGNED_OUT);
  }
}

function subscribe(listener) {
  listeners.add(listener);
  if (!started) { started = true; start(); }
  return () => listeners.delete(listener);
}

export function useCommonsIdentity() {
  return useSyncExternalStore(subscribe, () => state, () => state);
}

// Call after anything edits the name or photo so every header shows it.
export function refreshCommonsIdentity() {
  if (state.user) return loadProfile(state.user);
  return Promise.resolve();
}

export function showCommonsProfile(profile) {
  if (state.user && profile?.user_id === state.user.id) { generation += 1; set({ ...state, profile }); }
}

export async function signInToCommons() {
  const { auth } = await import('../supabase.js');
  await auth.signInWithGoogle(`${window.location.origin}${window.location.pathname}${window.location.search}`);
}

export async function signOutOfCommons() {
  const { auth } = await import('../supabase.js');
  await auth.signOut();
}

export function commonsSupabase() {
  return client;
}

// Tests only: forget the page's store between renders.
export function resetCommonsIdentityForTests() {
  state = { status: 'loading', user: null, profile: null };
  listeners.clear();
  started = false;
  client = null;
  generation = 0;
}
