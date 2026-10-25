import { act, cleanup, renderHook, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, expect, it, vi } from 'vitest';
import { useTripsAuth } from './useTripsAuth.js';

const mocked = vi.hoisted(() => ({ context: null, request: vi.fn() }));
vi.mock('../contexts/SupabaseContext.jsx', () => ({ useSupabase: () => mocked.context }));
vi.mock('./api.js', () => ({ tripRequest: (...args) => mocked.request(...args) }));
afterEach(cleanup);
beforeEach(() => { mocked.request.mockReset(); window.history.replaceState({}, '', '/trips'); });

function deferred() {
  let resolve, reject;
  const promise = new Promise((a, b) => { resolve = a; reject = b; });
  return { promise, resolve, reject };
}
function setup(initialSession = null, initialPromise) {
  let callback;
  const unsubscribe = vi.fn();
  const supabase = { auth: {
    getSession: vi.fn(() => initialPromise || Promise.resolve({ data: { session: initialSession } })),
    onAuthStateChange: vi.fn(listener => { callback = listener; return { data: { subscription: { unsubscribe } } }; }),
    signInWithPassword: vi.fn(),
  } };
  const auth = { signInWithGoogle: vi.fn().mockResolvedValue({}), signOut: vi.fn().mockResolvedValue({}) };
  mocked.context = { supabase, auth };
  return { supabase, auth, unsubscribe, emit: (event, session) => act(() => callback(event, session)) };
}
const session = id => ({ user: { id, user_metadata: { full_name: id } } });
const profile = id => ({ user_id: id, display_name: `Dice ${id}`, avatar_url: '/avatar.png', profile_source: 'dice' });

it('persists an owner confirmation and restores it from the account on a new session', async () => {
  const harness = setup(session('a'));
  let saved = { ...profile('a'), venmo_username: 'test-handle', venmo_confirmed: false };
  mocked.request.mockImplementation(async (_client, _path, method, payload) => {
    if (method === 'PUT') saved = { ...saved, venmo_username: payload.venmo_username, venmo_confirmed: true };
    return saved;
  });
  const first = renderHook(useTripsAuth);
  await waitFor(() => expect(first.result.current.profile?.venmo_confirmed).toBe(false));
  await act(() => first.result.current.saveVenmo('test-handle', true));
  expect(mocked.request).toHaveBeenCalledWith(harness.supabase, '/me', 'PUT', { venmo_username: 'test-handle', owner_confirmed: true }, 'a');
  expect(first.result.current.profile.venmo_confirmed).toBe(true);
  first.unmount();
  const next = renderHook(useTripsAuth);
  await waitFor(() => expect(next.result.current.profile?.venmo_confirmed).toBe(true));
});

it('restores the shared session and canonical profile using the existing client', async () => {
  const harness = setup(session('a'));
  mocked.request.mockResolvedValue(profile('a'));
  const { result } = renderHook(useTripsAuth);
  await waitFor(() => expect(result.current.profile?.display_name).toBe('Dice a'));
  expect(result.current.user.id).toBe('a');
  expect(result.current.supabase).toBe(harness.supabase);
  expect(mocked.request).toHaveBeenCalledWith(harness.supabase, '/me');
});

it('preserves the trip destination/query while keeping invitation secrets out of the OAuth return URL', async () => {
  const harness = setup();
  window.history.replaceState({}, '', '/trips/join/trip-id?view=people#invite=secret');
  const { result } = renderHook(useTripsAuth);
  await act(() => result.current.signIn());
  expect(harness.auth.signInWithGoogle).toHaveBeenCalledWith(`${window.location.origin}/trips/join/trip-id?view=people`);
  await act(() => result.current.signOut());
  expect(harness.auth.signOut).toHaveBeenCalledTimes(1);
});

it.each(['resolve', 'reject'])('ignores a stale initial session %s after a newer auth event', async outcome => {
  const initial = deferred();
  const harness = setup(null, initial.promise);
  mocked.request.mockResolvedValue(profile('new'));
  const { result } = renderHook(useTripsAuth);
  harness.emit('SIGNED_IN', session('new'));
  await waitFor(() => expect(result.current.profile?.user_id).toBe('new'));
  await act(async () => {
    if (outcome === 'resolve') initial.resolve({ data: { session: session('old') } });
    else initial.reject(new Error('Old session error'));
    await initial.promise.catch(() => {});
  });
  expect(result.current.user.id).toBe('new');
  expect(result.current.error).toBe('');
});

it('discards an old account profile response and clears identity on sign-out', async () => {
  const oldProfile = deferred();
  const harness = setup(session('a'));
  mocked.request.mockReturnValueOnce(oldProfile.promise).mockResolvedValueOnce(profile('b'));
  const { result } = renderHook(useTripsAuth);
  await waitFor(() => expect(mocked.request).toHaveBeenCalledTimes(1));
  harness.emit('SIGNED_IN', session('b'));
  expect(result.current.profile).toBeNull();
  await waitFor(() => expect(result.current.profile?.user_id).toBe('b'));
  await act(async () => oldProfile.resolve(profile('a')));
  expect(result.current.profile.user_id).toBe('b');
  harness.emit('SIGNED_OUT', null);
  expect(result.current.profile).toBeNull();
  expect(result.current.user).toBeNull();
});

it('shows a profile failure without destroying the shared session', async () => {
  const harness = setup(session('a'));
  mocked.request.mockRejectedValue(new Error('Network unavailable'));
  const { result } = renderHook(useTripsAuth);
  await waitFor(() => expect(result.current.error).toContain('Network unavailable'));
  expect(result.current.user.id).toBe('a');
  expect(harness.auth.signOut).not.toHaveBeenCalled();
});

it('rejects a mismatched profile identity', async () => {
  setup(session('a'));
  mocked.request.mockResolvedValue(profile('b'));
  const { result } = renderHook(useTripsAuth);
  await waitFor(() => expect(result.current.error).toContain('account changed'));
  expect(result.current.profile).toBeNull();
});

it('unsubscribes from the shared auth listener on unmount', () => {
  const harness = setup();
  const { unmount } = renderHook(useTripsAuth);
  unmount();
  expect(harness.unsubscribe).toHaveBeenCalledTimes(1);
});

it('does not offer synthetic password sign-in in the normal application', async () => {
  const harness = setup();
  const { result } = renderHook(useTripsAuth);
  await waitFor(() => expect(result.current.loading).toBe(false));
  await expect(result.current.signInLocal('Matt')).rejects.toThrow('Local demo is disabled');
  expect(harness.supabase.auth.signInWithPassword).not.toHaveBeenCalled();
});
