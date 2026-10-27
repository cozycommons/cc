import { act, renderHook, waitFor } from '@testing-library/react';
import { afterEach, expect, it, vi } from 'vitest';
import { usePlannerAuth } from './useFloorPlanDocument';

const context = vi.hoisted(() => ({
  supabase: { auth: {
    getSession: vi.fn().mockResolvedValue({ data: { session: null }, error: null }),
    onAuthStateChange: vi.fn(() => ({ data: { subscription: { unsubscribe: vi.fn() } } })),
  } },
  auth: { signInWithGoogle: vi.fn().mockResolvedValue({}) },
}));
vi.mock('../contexts/SupabaseContext', () => ({ useSupabase: () => context }));

afterEach(() => { window.history.replaceState({}, '', '/'); vi.clearAllMocks(); });

it('preserves the OAuth authorization request when signing in', async () => {
  window.history.replaceState({}, '', '/oauth/consent?authorization_id=request-1');
  const { result } = renderHook(() => usePlannerAuth());
  await waitFor(() => expect(result.current.loading).toBe(false));
  await act(() => result.current.signIn());
  expect(context.auth.signInWithGoogle).toHaveBeenCalledWith(`${window.location.origin}/oauth/consent?authorization_id=request-1`);
});
