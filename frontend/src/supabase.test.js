import { expect, it, vi } from 'vitest';
const client = vi.hoisted(() => ({ auth: { onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe() {} } } })) } }));
vi.mock('@supabase/supabase-js', () => ({ createClient: () => client }));
vi.mock('./runtimeConfig.js', () => ({ resolveRuntimeServiceUrl: () => 'http://127.0.0.1:54321' }));
it('registers an auth listener using the synchronous client', async () => {
  vi.stubEnv('VITE_SUPABASE_ANON_KEY', 'synthetic');
  const { auth } = await import('./supabase.js');
  const callback = vi.fn();
  const result = await auth.onAuthStateChange(callback);
  expect(client.auth.onAuthStateChange).toHaveBeenCalledWith(callback);
  expect(result.data.subscription.unsubscribe).toBeTypeOf('function');
  vi.unstubAllEnvs();
});
