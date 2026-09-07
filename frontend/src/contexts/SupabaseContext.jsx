import React, { createContext, useContext, useState } from 'react';
import { getClient as getSharedSupabaseClient } from '../supabase';

// Create the context
const SupabaseContext = createContext();

// Custom hook to use the context
export const useSupabase = () => {
    const context = useContext(SupabaseContext);
    if (!context) {
        throw new Error('useSupabase must be used within a SupabaseProvider');
    }
    return context;
};

// Provider component
export const SupabaseProvider = ({ children }) => {
    // Reuse the app-wide singleton client (src/supabase.js) instead of
    // creating a second GoTrueClient instance here. Two independent
    // clients pointed at the same project both try to auto-refresh and
    // persist to the same localStorage key, and can race and invalidate
    // each other's refresh token — a real cause of unexpected sign-outs.
    //
    // Client creation is synchronous (config is inlined at build time), so
    // it's created eagerly on first render instead of behind a loading
    // state that used to block the entire app tree from painting.
    const [state] = useState(() => {
        try {
            return { supabase: getSharedSupabaseClient(), error: null };
        } catch (err) {
            console.error('❌ Failed to initialize Supabase client:', err);
            return { supabase: null, error: err.message };
        }
    });
    const { supabase, error } = state;
    const loading = false;

    // Auth helper functions
    const auth = {
        // Get current user with session check
        getCurrentUser: async () => {
            if (!supabase) throw new Error('Supabase client not initialized');

            console.log('🔐 getCurrentUser: Starting session check...');

            try {
                // Check if client is ready by testing a simple operation
                console.log('🔐 getCurrentUser: Testing client readiness...');

                // Add timeout to prevent hanging
                const timeoutPromise = new Promise((_, reject) => {
                    setTimeout(() => reject(new Error('Session check timeout after 5 seconds')), 5000);
                });

                // First check if there's an active session with timeout
                console.log('🔐 getCurrentUser: Calling supabase.auth.getSession()...');
                const sessionPromise = supabase.auth.getSession();

                const { data: { session }, error: sessionError } = await Promise.race([
                    sessionPromise,
                    timeoutPromise
                ]);

                if (sessionError) {
                    console.log('🔐 getCurrentUser: Session error:', sessionError);
                    throw sessionError;
                }

                // If no session, return null. Note: getSession() already refreshes
                // an expired-but-refreshable access token internally, so there's no
                // need (and it's actively harmful) to re-check expires_at here and
                // force a sign-out — that raced the refresh and signed people out
                // of otherwise-valid sessions.
                if (!session) {
                    console.log('🔐 getCurrentUser: No active session found');
                    return null;
                }

                console.log('🔐 getCurrentUser: Active session found for user:', session.user.id);
                return session.user;
            } catch (error) {
                console.error('🔐 getCurrentUser: Error during session check:', error);
                throw error;
            }
        },

        // Get current session
        getSession: async () => {
            if (!supabase) throw new Error('Supabase client not initialized');
            const { data: { session }, error } = await supabase.auth.getSession();
            if (error) throw error;
            return session;
        },

        // Sign in with Google
        signInWithGoogle: async (redirectTo = null) => {
            if (!supabase) throw new Error('Supabase client not initialized');
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
            if (!supabase) throw new Error('Supabase client not initialized');
            const { error } = await supabase.auth.signOut();
            if (error) throw error;
        },

        // Listen to auth changes
        onAuthStateChange: (callback) => {
            if (!supabase) throw new Error('Supabase client not initialized');
            return supabase.auth.onAuthStateChange(callback);
        },

        // Get access token from current session
        getAccessToken: async () => {
            if (!supabase) throw new Error('Supabase client not initialized');
            const { data: { session }, error } = await supabase.auth.getSession();
            if (error) throw error;
            return session?.access_token || null;
        }
    };

    // Profile helper functions
    const profiles = {
        // Get user profile
        getProfile: async (userId) => {
            if (!supabase) throw new Error('Supabase client not initialized');
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
            if (!supabase) throw new Error('Supabase client not initialized');
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
            if (!supabase) throw new Error('Supabase client not initialized');
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

    // Value object to provide to consumers
    const value = {
        supabase,
        auth,
        profiles,
        loading,
        error
    };

    if (error) {
        return (
            <div className="min-h-screen flex items-center justify-center">
                <div className="text-center">
                    <div className="text-red-600 text-xl mb-4">❌ Supabase Initialization Failed</div>
                    <p className="text-gray-600 mb-4">{error}</p>
                    <button
                        onClick={() => window.location.reload()}
                        className="px-4 py-2 bg-blue-600 text-white rounded hover:bg-blue-700"
                    >
                        Retry
                    </button>
                </div>
            </div>
        );
    }

    return (
        <SupabaseContext.Provider value={value}>
            {children}
        </SupabaseContext.Provider>
    );
};
