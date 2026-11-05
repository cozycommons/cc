import { expect, it, vi } from 'vitest';
import { credentialImage } from './credentialImages.js';

it('uses a local avatar for arbitrary remote profiles on credential pages', () => {
  vi.stubEnv('VITE_SUPABASE_URL', 'https://auth.example.test');
  expect(credentialImage('https://untrusted.example/avatar', '/account')).toBeNull();
  expect(credentialImage('https://untrusted.example/avatar', '/dice')).toBe('https://untrusted.example/avatar');
  expect(credentialImage('https://auth.example.test/storage/v1/avatar', '/account')).toBe('https://auth.example.test/storage/v1/avatar');
  expect(credentialImage('https://lh3.googleusercontent.com/photo', '/account')).toBe('https://lh3.googleusercontent.com/photo');
  vi.unstubAllEnvs();
});
