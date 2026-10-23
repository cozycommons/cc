import { useEffect, useState } from 'react';
import { useSupabase } from '../contexts/SupabaseContext.jsx';
import { tripRequest } from './api.js';

export const localDemo = import.meta.env.DEV && import.meta.env.VITE_TRIPS_LOCAL_DEMO === 'true';

export function useTripsAuth() {
  const { supabase, auth } = useSupabase();
  const [state, setState] = useState({ loading: true, user: null, error: '' });
  const [identity, setIdentity] = useState({ userId: null, profile: null, error: '' });
  useEffect(() => {
    let active = true;
    let version = 0;
    const initialVersion = version;
    supabase.auth.getSession().then(({ data, error }) => {
      if (active && version === initialVersion) setState({ loading: false, user: data.session?.user ?? null, error: error?.message || '' });
    }).catch((error) => {
      if (active && version === initialVersion) setState({ loading: false, user: null, error: error.message });
    });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      version += 1;
      if (active) setState({ loading: false, user: session?.user ?? null, error: '' });
    });
    return () => { active = false; subscription.unsubscribe(); };
  }, [supabase]);
  const userId = state.user?.id;
  useEffect(() => {
    let active = true;
    if (!userId) return () => { active = false; };
    tripRequest(supabase, '/me').then(profile => {
      if (profile.user_id !== userId) throw new Error('Your account changed. Reload the trip to continue.');
      if (active) setIdentity({ userId, profile, error: '' });
    }).catch(error => {
      if (active) setIdentity({ userId, profile: null, error: `Could not load your Commons profile: ${error.message}` });
    });
    return () => { active = false; };
  }, [supabase, userId]);
  const profile = identity.userId === userId ? identity.profile : null;
  return { ...state, supabase, profile,
    error: state.error || (identity.userId === userId ? identity.error : ''),
    signIn: () => auth.signInWithGoogle(`${window.location.origin}${window.location.pathname}${window.location.search}`),
    signOut: () => auth.signOut(),
    // Writes only the caller's own account. A response for an account that has since signed out is dropped.
    saveVenmo: async (username) => {
      if (!userId) throw new Error('Please sign in again to continue.');
      const saved = await tripRequest(supabase, '/me', 'PUT', { venmo_username: username }, userId);
      if (saved.user_id !== userId) throw new Error('Your account changed. Reload to continue.');
      setIdentity((current) => (current.userId === saved.user_id ? { ...current, profile: saved, error: '' } : current));
      return saved;
    },
    signInLocal: async (name) => {
      if (!localDemo) throw new Error('Local demo is disabled.');
      const { error } = await supabase.auth.signInWithPassword({ email: `${name.toLowerCase()}@trips.local`, password: 'local-trips-password' });
      if (error) throw error;
    },
  };
}
