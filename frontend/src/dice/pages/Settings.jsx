import React, { useState } from 'react';
import { Link } from 'react-router-dom';
import { diceApi } from '../api.js';

const ANONYMOUS_CONFIRM = 'Play anonymously? Your games still count everywhere, but on results, leaderboards and stats others will see a random animal instead of your name. Player pickers and live games still show your name.';

// Account settings live here rather than on the profile, so a privacy change
// is a deliberate visit and never a stray tap on your own profile page.
export default function Settings({ auth }) {
  const { token, profile, refreshProfile } = auth;
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState(null);
  const anonymous = Boolean(profile?.is_anonymous);

  const toggleAnonymous = async () => {
    if (!token) return;
    const turningOn = !anonymous;
    if (turningOn && !window.confirm(ANONYMOUS_CONFIRM)) return;
    setSaving(true);
    setError(null);
    try {
      await diceApi.updateMyProfile(token, { is_anonymous: turningOn });
      await refreshProfile();
    } catch {
      setError('Failed to save setting.');
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="max-w-xl mx-auto px-4 sm:px-6 py-8">
      <h1 className="jk-display text-3xl mb-6">Settings</h1>
      <p className="jk-label mb-3">// PRIVACY</p>
      <div className="jk-card p-4">
        <label className="flex items-center gap-2" style={{ fontFamily: 'var(--font-body)', fontSize: 14, color: 'var(--text-primary)' }}>
          <input type="checkbox" checked={anonymous} onChange={toggleAnonymous} disabled={saving} />
          Play anonymously
        </label>
        <p className="text-xs mt-2" style={{ color: 'var(--text-tertiary)' }}>
          Only changes how your name is shown. Your games and ratings still count in every leaderboard and stat.
          On results, leaderboards and stats others see a random animal (like “Anonymous Otter”) that reshuffles
          each visit. Player pickers and live games still show your name, and your profile becomes private.
        </p>
        {error && <p role="alert" className="mt-2" style={{ color: 'var(--state-danger)', fontSize: 12 }}>{error}</p>}
      </div>
      {profile?.user_id && (
        <Link className="jk-label underline inline-block mt-6" to={`/dice/profile/${profile.user_id}`}>← Your profile</Link>
      )}
    </div>
  );
}
