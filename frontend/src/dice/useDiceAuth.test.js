import { describe, expect, it } from 'vitest';
import {
  canUseSyntheticDiceAccount,
  DEFAULT_DICE_FEATURES,
  normalizeDiceFeatures,
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

describe('normalizeDiceFeatures', () => {
  it('fails closed when access is missing or malformed', () => {
    expect(normalizeDiceFeatures()).toEqual(DEFAULT_DICE_FEATURES);
    expect(normalizeDiceFeatures({ dice_live_referee: 'true' })).toEqual(DEFAULT_DICE_FEATURES);
  });

  it('keeps only known boolean capabilities', () => {
    expect(normalizeDiceFeatures({
      dice_live_referee: { opted_in: true, effective: true },
      future_flag: { opted_in: true, effective: true },
    })).toEqual({
      dice_live_referee: { opted_in: true, effective: true },
    });
  });
});
