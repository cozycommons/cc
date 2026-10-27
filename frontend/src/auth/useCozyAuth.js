import { useEffect, useState } from 'react';
import { useSupabase } from '../contexts/SupabaseContext';

export function useCozyAuth() {
  const { supabase, auth } = useSupabase();
  const [state, setState] = useState({ loading: true, user: null });
  useEffect(() => {
    let active = true;
    let version = 0;
    const initialVersion = version;
    supabase.auth.getSession().then(({ data, error }) => {
      if (active && version === initialVersion) setState({ loading: false, user: error ? null : data.session?.user ?? null });
    }).catch(() => { if (active && version === initialVersion) setState({ loading: false, user: null }); });
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      version += 1;
      if (active) setState({ loading: false, user: session?.user ?? null });
    });
    return () => { active = false; subscription.unsubscribe(); };
  }, [supabase]);
  return { ...state, supabase, signIn: () => auth.signInWithGoogle(`${window.location.origin}${window.location.pathname}${window.location.search}`) };
}
