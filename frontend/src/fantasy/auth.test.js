import { afterEach, beforeEach, expect, it, vi } from 'vitest';

const client = vi.hoisted(() => ({
  getSession: vi.fn(async () => ({ access_token: 'fresh' })),
  signInWithGoogle: vi.fn(),
  onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })),
}));
vi.mock('../supabase', () => ({ auth: client }));
let auth, hasAuthHint;
beforeEach(async () => {
  vi.resetModules();
  vi.clearAllMocks();
  localStorage.clear();
  window.history.replaceState({}, '', '/fantasy');
  ({ auth, hasAuthHint } = await import('./auth.js'));
});
afterEach(() => { vi.restoreAllMocks(); window.history.replaceState({}, '', '/'); localStorage.clear(); });

it('anonymous checks and subscriptions never initialize the client', async () => {
  const result = await auth.onAuthStateChange(vi.fn());
  expect(await auth.getSession()).toBeNull();
  expect(client.getSession).not.toHaveBeenCalled();
  expect(client.onAuthStateChange).not.toHaveBeenCalled();
  result.data.subscription.unsubscribe();
});
it('only uses the configured project session key, including local hosts', () => {
  localStorage.setItem('sb-other-auth-token', '{}');
  localStorage.setItem('sb-project-auth-token-code-verifier', 'value');
  expect(hasAuthHint('https://project.supabase.co')).toBe(false);
  localStorage.setItem('sb-project-auth-token', '{}');
  expect(hasAuthHint('https://project.supabase.co')).toBe(true);
  localStorage.setItem('sb-127-auth-token', '{}');
  expect(hasAuthHint('http://127.0.0.1:54321')).toBe(true);
});
it.each(['?code=x', '#access_token=x', '?error=denied', '#error_description=denied', '#error_code=x'])('loads auth on callback %s', async marker => {
  window.history.replaceState({}, '', `/fantasy${marker}`);
  expect(hasAuthHint()).toBe(true);
  expect(await auth.getSession()).toEqual({ access_token: 'fresh' });
});
it('treats storage denial as anonymous but preserves callbacks and explicit sign-in', async () => {
  vi.spyOn(Storage.prototype, 'getItem').mockImplementation(() => { throw new Error('denied'); });
  expect(hasAuthHint('https://project.supabase.co')).toBe(false);
  expect(await auth.getSession()).toBeNull();
  await auth.signInWithGoogle('https://example.test/fantasy');
  expect(client.signInWithGoogle).toHaveBeenCalledWith('https://example.test/fantasy');
  window.history.replaceState({}, '', '/fantasy?code=x');
  expect(hasAuthHint()).toBe(true);
});
it('starts waiting observers on cross-tab login and cleans up', async () => {
  const callback = vi.fn();
  const result = await auth.onAuthStateChange(callback);
  window.history.replaceState({}, '', '/fantasy?code=x');
  window.dispatchEvent(new StorageEvent('storage'));
  await vi.waitFor(() => expect(client.onAuthStateChange).toHaveBeenCalledWith(callback));
  result.data.subscription.unsubscribe();
  expect(client.onAuthStateChange.mock.results[0].value.data.subscription.unsubscribe).toHaveBeenCalledOnce();
});
it('explicit sign-in starts existing anonymous observers', async () => {
  const callback = vi.fn();
  const result = await auth.onAuthStateChange(callback);
  await auth.signInWithGoogle();
  await vi.waitFor(() => expect(client.onAuthStateChange).toHaveBeenCalledWith(callback));
  result.data.subscription.unsubscribe();
});
