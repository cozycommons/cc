import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => {
  const getSession = vi.fn();
  const onAuthStateChange = vi.fn();
  return {
    getMyProfile: vi.fn(),
    getMyFeatures: vi.fn(),
    updateMyFeature: vi.fn(),
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
    getMyFeatures: mocks.getMyFeatures,
    updateMyFeature: mocks.updateMyFeature,
  },
}));

import { useDiceAuth } from './useDiceAuth.js';

const session = {
  user: { id: 'u1', email: 'player@example.com' },
  access_token: 'token',
};

describe('useDiceAuth feature loading', () => {
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

  it('loads effective capabilities with the existing Dice session', async () => {
    arrange();
    mocks.getMyFeatures.mockResolvedValue({
      dice_live_referee: { opted_in: true, effective: true },
    });

    const { result } = renderHook(() => useDiceAuth());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(mocks.getMyFeatures).toHaveBeenCalledWith('token');
    expect(result.current.features).toEqual({
      dice_live_referee: { opted_in: true, effective: true },
    });
  });

  it('fails closed without blocking profile loading when capabilities fail', async () => {
    arrange();
    mocks.getMyFeatures.mockRejectedValue(new Error('unavailable'));

    const { result } = renderHook(() => useDiceAuth());

    await waitFor(() => expect(result.current.loading).toBe(false));
    expect(result.current.profile).toEqual({ user_id: 'u1', display_name: 'Player' });
    expect(result.current.features).toEqual({
      dice_live_referee: { opted_in: false, effective: false },
    });
  });

  it('clears prior access immediately when the signed-in account changes', async () => {
    arrange();
    let authChange;
    mocks.onAuthStateChange.mockImplementation((handler) => {
      authChange = handler;
      return { data: { subscription: { unsubscribe: vi.fn() } } };
    });
    mocks.getMyFeatures
      .mockResolvedValueOnce({
        dice_live_referee: { opted_in: true, effective: true },
      })
      .mockRejectedValueOnce(new Error('unavailable'));

    const { result } = renderHook(() => useDiceAuth());
    await waitFor(() => expect(result.current.features.dice_live_referee.effective).toBe(true));

    await act(async () => {
      authChange('SIGNED_IN', {
        user: { id: 'u2', email: 'other@example.com' },
        access_token: 'other-token',
      });
    });

    await waitFor(() => expect(result.current.user.id).toBe('u2'));
    expect(result.current.features).toEqual({
      dice_live_referee: { opted_in: false, effective: false },
    });
  });

  it('does not hydrate the initial session twice', async () => {
    arrange();
    let authChange;
    mocks.onAuthStateChange.mockImplementation((handler) => {
      authChange = handler;
      return { data: { subscription: { unsubscribe: vi.fn() } } };
    });
    mocks.getMyFeatures.mockResolvedValue({
      dice_live_referee: { opted_in: true, effective: true },
    });

    const { result } = renderHook(() => useDiceAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));
    await act(async () => authChange('INITIAL_SESSION', session));

    expect(mocks.getMyProfile).toHaveBeenCalledTimes(1);
    expect(mocks.getMyFeatures).toHaveBeenCalledTimes(1);
  });

  it('updates the signed-in user preference through the self endpoint', async () => {
    arrange();
    mocks.getMyFeatures.mockResolvedValue({
      dice_live_referee: { opted_in: false, effective: false },
    });
    mocks.updateMyFeature.mockResolvedValue({
      dice_live_referee: { opted_in: true, effective: true },
    });

    const { result } = renderHook(() => useDiceAuth());
    await waitFor(() => expect(result.current.loading).toBe(false));

    await act(() => result.current.updateFeature('dice_live_referee', true));

    expect(mocks.updateMyFeature).toHaveBeenCalledWith('token', 'dice_live_referee', true);
    expect(result.current.features).toEqual({
      dice_live_referee: { opted_in: true, effective: true },
    });
  });
});
