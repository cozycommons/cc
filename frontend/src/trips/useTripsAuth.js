import { useEffect, useState } from 'react';
import { useSupabase } from '../contexts/SupabaseContext.jsx';

export const localDemo = import.meta.env.DEV && import.meta.env.VITE_TRIPS_LOCAL_DEMO === 'true';

export function useTripsAuth() {
  const { supabase, auth } = useSupabase();
  const [state, setState] = useState({ loading: true, user: null, error: '' });
  useEffect(() => {
    let active = true;
    let version = 0;
    const initialVersion = version;
    supabase.auth.getSession().then(({ data, error }) => {
      if (active && version === initialVersion) setState({ loading: false, user: data.session?.user ?? null, error: error?.message || '' });
    }).catch((error) => {
      if (active) setState({ loading: false, user: null, error: error.message });
    });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      version += 1;
      if (active) setState({ loading: false, user: session?.user ?? null, error: '' });
    });
    return () => { active = false; subscription.unsubscribe(); };
  }, [supabase]);
  return { ...state, supabase,
    signIn: () => auth.signInWithGoogle(`${window.location.origin}${window.location.pathname}`),
    signOut: () => auth.signOut(),
    signInLocal: async (name) => {
      if (!localDemo) throw new Error('Local demo is disabled.');
      const { error } = await supabase.auth.signInWithPassword({ email: `${name.toLowerCase()}@trips.local`, password: 'local-trips-password' });
      if (error) throw error;
    },
  };
}
