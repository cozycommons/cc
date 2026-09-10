import { describe, expect, it } from 'vitest';
import {
  canUseSyntheticDiceAccount,
} from './useDiceAuth.js';

const base = {
  dev: true,
  mode: 'development',
  localHarness: true,
  supabaseUrl: 'http://127.0.0.1:54321',
  codespacesOrigin: '',
  browserOrigin: 'http://localhost:8080',
  email: 'referee@dice.local',
  password: 'local-dice-password',
};

describe('canUseSyntheticDiceAccount', () => {
  it('allows the exact loopback harness', () => {
    expect(canUseSyntheticDiceAccount(base)).toBe(true);
  });

  it.each([
    'http://localhost:8083',
    'http://127.0.0.1:49152',
  ])('allows a loopback harness on alternate unprivileged port %s', (browserOrigin) => {
    expect(canUseSyntheticDiceAccount({ ...base, browserOrigin })).toBe(true);
  });

  it('allows an exact same-origin Codespaces sandbox', () => {
    const origin = 'https://friendly-space-8080.app.github.dev';
    expect(canUseSyntheticDiceAccount({
      ...base,
      supabaseUrl: origin,
      codespacesOrigin: origin,
      browserOrigin: origin,
    })).toBe(true);
  });

  it('allows the exact loopback route used by in-sandbox browser tests', () => {
    expect(canUseSyntheticDiceAccount({
      ...base,
      supabaseUrl: 'http://127.0.0.1:8080',
      codespacesOrigin: 'https://friendly-space-8080.app.github.dev',
      browserOrigin: 'http://127.0.0.1:8080',
    })).toBe(true);
  });

  it.each([
    { mode: 'production' },
    { dev: false },
    { localHarness: false },
    { supabaseUrl: 'https://example.supabase.co' },
    { browserOrigin: 'https://attacker.example' },
    { browserOrigin: 'http://localhost' },
    { browserOrigin: 'http://localhost:80' },
    { browserOrigin: 'http://127.0.0.1:65536' },
    { browserOrigin: 'http://localhost:8083/path' },
    { browserOrigin: 'http://localhost.example:8083' },
    {
      supabaseUrl: 'http://127.0.0.1:49152',
      codespacesOrigin: 'https://friendly-space-8080.app.github.dev',
      browserOrigin: 'http://127.0.0.1:49152',
    },
    {
      supabaseUrl: 'https://friendly-space-8080.app.github.dev',
      codespacesOrigin: 'https://friendly-space-8080.app.github.dev',
      browserOrigin: 'https://attacker.example',
    },
    { email: '' },
    { password: '' },
  ])('rejects unsafe synthetic login configuration: %o', (override) => {
    expect(canUseSyntheticDiceAccount({ ...base, ...override })).toBe(false);
  });
});
