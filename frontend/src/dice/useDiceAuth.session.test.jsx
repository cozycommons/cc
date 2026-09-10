import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => {
  const getSession = vi.fn();
  const onAuthStateChange = vi.fn();
  return {
    getMyProfile: vi.fn(),
    getSession,
    onAuthStateChange,
    supabase: { auth: { getSession, onAuthStateChange } },
  };
});

vi.mock('../contexts/SupabaseContext', () => ({
  useSupabase: () => ({ supabase: mocks.supabase }),
}));

vi.mock('./api.js', () => ({
  diceApi: {
    getMyProfile: mocks.getMyProfile,
  },
}));

import { useDiceAuth } from './useDiceAuth.js';

const session = {
  user: { id: 'u1', email: 'player@example.com' },
  access_token: 'token',
};

describe('useDiceAuth session loading', () => {
  afterEach(() => {
    vi.restoreAllMocks();
    vi.clearAllMocks();
  });

  function arrange() {
    vi.spyOn(console, 'error').mockImplementation(() => {});
    mocks.getSession.mockResolvedValue({ data: { session } });
    mocks.onAuthStateChange.mockReturnValue({
      data: { subscription: { unsubscribe: vi.fn() } },
    });
    mocks.getMyProfile.mockResolvedValue({ user_id: 'u1', display_name: 'Player' });
  }

  it('loads the profile without a rollout-feature request', async () => {
    arrange();

    const { result } = renderHook(() => useDiceAuth());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.profile).toEqual({ user_id: 'u1', display_name: 'Player' });
    expect(result.current.features).toBeUndefined();
  });

  it('does not hydrate the initial session twice', async () => {
    arrange();
    let authChange;
    mocks.onAuthStateChange.mockImplementation((handler) => {
      authChange = handler;
      return { data: { subscription: { unsubscribe: vi.fn() } } };
    });
    const { result } = renderHook(() => useDiceAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => authChange('INITIAL_SESSION', session));

    expect(mocks.getMyProfile).toHaveBeenCalledTimes(1);
  });

  it('clears the previous profile and stays loading until an account switch resolves', async () => {
    arrange();
    let authChange;
    let resolveSecondProfile;
    mocks.onAuthStateChange.mockImplementation((handler) => {
      authChange = handler;
      return { data: { subscription: { unsubscribe: vi.fn() } } };
    });
    const { result } = renderHook(() => useDiceAuth());
    await waitFor(() => expect(result.current.profile?.user_id).toBe('u1'));

    mocks.getMyProfile.mockImplementationOnce(() => new Promise((resolve) => {
      resolveSecondProfile = resolve;
    }));
    act(() => {
      authChange('SIGNED_IN', {
        user: { id: 'u2', email: 'other@example.com' },
        access_token: 'other-token',
      });
    });

    expect(result.current.user.id).toBe('u2');
    expect(result.current.profile).toBeNull();
    expect(result.current.loading).toBe(true);

    await act(async () => resolveSecondProfile({ user_id: 'u2', display_name: 'Other' }));
    expect(result.current.profile.user_id).toBe('u2');
    expect(result.current.loading).toBe(false);
  });

  it('does not let a delayed initial session replace a newer auth event', async () => {
    arrange();
    let authChange;
    let resolveInitialSession;
    mocks.getSession.mockReturnValue(new Promise((resolve) => {
      resolveInitialSession = resolve;
    }));
    mocks.onAuthStateChange.mockImplementation((handler) => {
      authChange = handler;
      return { data: { subscription: { unsubscribe: vi.fn() } } };
    });
    mocks.getMyProfile.mockResolvedValueOnce({ user_id: 'u2', display_name: 'Other' });
    const { result } = renderHook(() => useDiceAuth());

    await act(async () => authChange('SIGNED_IN', {
      user: { id: 'u2', email: 'other@example.com' },
      access_token: 'other-token',
    }));
    await waitFor(() => expect(result.current.profile?.user_id).toBe('u2'));

    await act(async () => resolveInitialSession({ data: { session } }));
    expect(result.current.user.id).toBe('u2');
    expect(result.current.token).toBe('other-token');
    expect(result.current.profile.user_id).toBe('u2');
  });

  it('discards a manual profile refresh that resolves after an account switch', async () => {
    arrange();
    let authChange;
    let resolveRefresh;
    mocks.onAuthStateChange.mockImplementation((handler) => {
      authChange = handler;
      return { data: { subscription: { unsubscribe: vi.fn() } } };
    });
    const { result } = renderHook(() => useDiceAuth());
    await waitFor(() => expect(result.current.profile?.user_id).toBe('u1'));

    mocks.getMyProfile
      .mockImplementationOnce(() => new Promise((resolve) => { resolveRefresh = resolve; }))
      .mockResolvedValueOnce({ user_id: 'u2', display_name: 'Other' });
    let refresh;
    act(() => { refresh = result.current.refreshProfile(); });
    await act(async () => authChange('SIGNED_IN', {
      user: { id: 'u2', email: 'other@example.com' },
      access_token: 'other-token',
    }));
    await waitFor(() => expect(result.current.profile?.user_id).toBe('u2'));

    await act(async () => resolveRefresh({ user_id: 'u1', display_name: 'Old' }));
    await expect(refresh).resolves.toBeUndefined();
    expect(result.current.profile.user_id).toBe('u2');
  });
});
