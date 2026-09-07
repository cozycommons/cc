import { createClient } from '@supabase/supabase-js';
import { resolveRuntimeServiceUrl } from './runtimeConfig.js';

let supabaseClient = null;

// Vite's `define` (see vite.config.js) inlines these as literal strings at
// build time, so reading them is synchronous — no need to fetch config.json
// over the network before the client can be created.
function getSupabaseClient() {
    if (supabaseClient) {
        return supabaseClient;
    }

    const supabaseUrl = resolveRuntimeServiceUrl(import.meta.env.VITE_SUPABASE_URL);
    const supabaseAnonKey = import.meta.env.VITE_SUPABASE_ANON_KEY;

    if (!supabaseUrl || !supabaseAnonKey) {
        throw new Error('VITE_SUPABASE_URL or VITE_SUPABASE_ANON_KEY is missing');
    }

    supabaseClient = createClient(supabaseUrl, supabaseAnonKey, {
        auth: {
            // These are supabase-js's defaults, made explicit: keep the
            // session in localStorage across reloads/tabs, and proactively
            // refresh the access token in the background so a session
            // started once keeps working indefinitely (until sign-out or
            // refresh-token revocation) instead of dying with the ~1hr
            // access token.
            persistSession: true,
            autoRefreshToken: true,
            detectSessionInUrl: true,
        },
    });

    return supabaseClient;
}

// Auth helper functions
export const auth = {
    // Get current user
    getCurrentUser: async () => {
        const supabase = await getSupabaseClient();
        const { data: { user }, error } = await supabase.auth.getUser();
        if (error) throw error;
        return user;
    },

    // Get current session
    getSession: async () => {
        const supabase = await getSupabaseClient();
        const { data: { session }, error } = await supabase.auth.getSession();
        if (error) throw error;
        return session;
    },

    // Sign in with Google
    signInWithGoogle: async (redirectTo = null) => {
        const supabase = await getSupabaseClient();
        const { data, error } = await supabase.auth.signInWithOAuth({
            provider: 'google',
            options: {
                redirectTo: redirectTo || `${window.location.origin}${window.location.pathname}`
            }
        });
        if (error) throw error;
        return data;
    },

    // Sign out
    signOut: async () => {
        const supabase = await getSupabaseClient();
        const { error } = await supabase.auth.signOut();
        if (error) throw error;
    },

    // Listen to auth changes - returns subscription object directly
    onAuthStateChange: (callback) => {
        // Return a promise that resolves to the subscription
        return getSupabaseClient().then(supabase => {
            return supabase.auth.onAuthStateChange(callback);
        });
    }
};

// Profile helper functions for pickle app
export const profiles = {
    // Get user profile
    getProfile: async (userId) => {
        const supabase = await getSupabaseClient();
        const { data, error } = await supabase
            .from('pickle_user_profile')
            .select('*')
            .eq('user_id', userId)
            .single();

        if (error && error.code !== 'PGRST116') throw error; // PGRST116 = no rows returned
        return data;
    },

    // Update user profile
    updateProfile: async (userId, profileData) => {
        const supabase = await getSupabaseClient();
        const { data, error } = await supabase
            .from('pickle_user_profile')
            .upsert({
                user_id: userId,
                ...profileData,
                updated_at: new Date().toISOString()
            })
            .select()
            .single();

        if (error) throw error;
        return data;
    },

    // Create default profile
    createDefaultProfile: async (userId) => {
        const supabase = await getSupabaseClient();
        const defaultProfile = {
            user_id: userId,
            display_name: `Player ${userId.slice(0, 8)}`,
            avatar_url: null,
            created_at: new Date().toISOString(),
            updated_at: new Date().toISOString()
        };

        const { data, error } = await supabase
            .from('pickle_user_profile')
            .insert(defaultProfile)
            .select()
            .single();

        if (error) throw error;
        return data;
    }
};

// Export the raw client for advanced usage
export const getClient = getSupabaseClient;

// Default export for backward compatibility
export default getSupabaseClient;
