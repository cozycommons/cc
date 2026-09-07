import React, { useEffect, useState } from 'react';
import { useParams } from 'react-router-dom';
import { LogOut } from 'lucide-react';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { useSupabase } from '../../contexts/SupabaseContext';
import { diceApi } from '../api.js';
import PlayerAvatar from '../components/PlayerAvatar.jsx';
import { AVATAR_IMAGE_MAX_EDGE, compactImage, uniqueImageFolder } from '../imageUpload.js';
import GameRow from '../components/GameRow.jsx';
import EloHistoryChart from '../components/EloHistoryChart.jsx';

const AVATAR_BUCKET = 'dice-profile-photos';

// Normalizes a loosely-formatted US number to E.164 (+1XXXXXXXXXX) to match
// what the backend requires for Twilio. Returns null if it can't.
function toE164(raw) {
  const trimmed = (raw || '').trim();
  if (!trimmed) return '';
  const digits = trimmed.replace(/\D/g, '');
  if (trimmed.startsWith('+') && digits.length >= 8 && digits.length <= 15) return `+${digits}`;
  if (digits.length === 10) return `+1${digits}`;
  if (digits.length === 11 && digits.startsWith('1')) return `+${digits}`;
  return null;
}

function StatTile({ label, value, badge }) {
  return (
    <div className="jk-card p-4 flex flex-col items-center text-center">
      <span className="jk-display" style={{ fontSize: 26, lineHeight: 1.1 }}>{value}</span>
      {badge}
      <span className="jk-label mt-1">{label}</span>
    </div>
  );
}

function ProvisionalBadge({ gamesRemaining }) {
  return (
    <span
      title={`Provisional: ${gamesRemaining} more ranked game${gamesRemaining === 1 ? '' : 's'} to go before this ELO counts toward the leaderboard`}
      className="mt-1"
      style={{
        fontFamily: 'var(--font-mono)',
        fontSize: 9,
        fontWeight: 600,
        color: 'var(--text-on-strong)',
        background: 'var(--surface-strong)',
        borderRadius: 3,
        padding: '1px 6px',
        letterSpacing: '0.03em',
        whiteSpace: 'nowrap',
      }}
    >
      PROVISIONAL
    </span>
  );
}

export default function PlayerProfile({ auth }) {
  const { userId } = useParams();
  const { supabase } = useSupabase();
  const { user, token, features, isAdmin, refreshProfile, updateFeature, signOut } = auth;
  const [profile, setProfile] = useState(null);
  const [games, setGames] = useState(null);
  const [ratingProgress, setRatingProgress] = useState(undefined);
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState('');
  const [saving, setSaving] = useState(false);
  const [uploading, setUploading] = useState(false);
  const [savingSetting, setSavingSetting] = useState(false);
  const [error, setError] = useState(null);
  const [phone, setPhone] = useState('');
  const [smsEnabled, setSmsEnabled] = useState(false);
  const [savingSms, setSavingSms] = useState(false);
  const [smsError, setSmsError] = useState(null);
  const [smsSaved, setSmsSaved] = useState(false);
  const [savingFeature, setSavingFeature] = useState(false);
  const [featureError, setFeatureError] = useState(null);

  const isOwnProfile = user?.id === userId;
  const canEdit = isOwnProfile || isAdmin;
  const liveReferee = features?.dice_live_referee ?? { opted_in: false, effective: false };

  const load = () => {
    setRatingProgress(undefined);
    diceApi.getProfile(userId, token).then((p) => {
      setProfile(p);
      setName(p.display_name);
      setPhone(p.phone_number || '');
      setSmsEnabled(p.sms_notifications_enabled);
    }).catch(() => setProfile(null));
    diceApi.getProfileGames(userId, 100).then(setGames).catch(() => setGames([]));
    diceApi.getRatingProgress(userId).then(setRatingProgress).catch(() => setRatingProgress(null));
  };

  useEffect(() => {
    load();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [userId, token]);

  const eloHistory = ratingProgress?.history
    ? ratingProgress.history.map((point) => ({ date: point.played_at, elo: point.rating_after }))
    : ratingProgress === undefined || !games
      ? null
      : games
        .map((game) => {
          const player = game.players.find((item) => item.user_id === userId);
          return player?.elo_after != null ? { date: game.played_at, elo: player.elo_after } : null;
        })
        .filter(Boolean)
        .sort((first, second) => new Date(first.date) - new Date(second.date));
  const ratingDeltaByGame = new Map(
    ratingProgress?.history.map((point) => [point.game_id, point.delta]) ?? [],
  );

  const saveName = async () => {
    if (!token) return;
    setSaving(true);
    setError(null);
    try {
      const payload = { display_name: name };
      if (!isOwnProfile && isAdmin) payload.user_id = userId;
      const updated = await diceApi.updateMyProfile(token, payload);
      setProfile(updated);
      setEditing(false);
      if (isOwnProfile) await refreshProfile();
    } catch (err) {
      setError('Failed to save name.');
    } finally {
      setSaving(false);
    }
  };

  const uploadAvatar = async (e) => {
    const file = e.target.files?.[0];
    if (!file || !token || !supabase) return;
    setUploading(true);
    setError(null);
    try {
      const avatar = await compactImage(file, { maxEdge: AVATAR_IMAGE_MAX_EDGE, quality: 0.8 });
      const path = `${uniqueImageFolder(userId)}/avatar.webp`;
      const { error: uploadError } = await supabase.storage
        .from(AVATAR_BUCKET)
        .upload(path, avatar, {
          contentType: 'image/webp',
          cacheControl: '31536000',
          upsert: false,
        });
      if (uploadError) throw uploadError;
      const { data } = supabase.storage.from(AVATAR_BUCKET).getPublicUrl(path);
      const payload = { avatar_url: data.publicUrl };
      if (!isOwnProfile && isAdmin) payload.user_id = userId;
      const updated = await diceApi.updateMyProfile(token, payload);
      setProfile(updated);
      if (isOwnProfile) await refreshProfile();
    } catch (err) {
      const expectedMessage = err?.message?.startsWith('Use a ')
        || err?.message?.startsWith('Image must')
        || err?.message?.startsWith('That image')
        || err?.message?.startsWith('This browser');
      setError(expectedMessage ? err.message : 'Failed to upload photo.');
    } finally {
      setUploading(false);
    }
  };

  const toggleHideFromLeaderboard = async () => {
    if (!token) return;
    setSavingSetting(true);
    setError(null);
    try {
      const payload = { hide_from_leaderboard: !profile.hide_from_leaderboard };
      if (!isOwnProfile && isAdmin) payload.user_id = userId;
      const updated = await diceApi.updateMyProfile(token, payload);
      setProfile(updated);
      if (isOwnProfile) await refreshProfile();
    } catch (err) {
      setError('Failed to save setting.');
    } finally {
      setSavingSetting(false);
    }
  };

  const saveSmsSettings = async () => {
    if (!token) return;
    setSmsError(null);
    setSmsSaved(false);

    const normalizedPhone = toE164(phone);
    if (normalizedPhone === null) {
      setSmsError('Enter a valid phone number, e.g. (415) 555-1234.');
      return;
    }
    if (smsEnabled && !normalizedPhone) {
      setSmsError('Add a phone number to get texted your game results.');
      return;
    }

    setSavingSms(true);
    try {
      const payload = { phone_number: normalizedPhone, sms_notifications_enabled: smsEnabled };
      const updated = await diceApi.updateMyProfile(token, payload);
      setProfile(updated);
      setPhone(updated.phone_number || '');
      setSmsEnabled(updated.sms_notifications_enabled);
      setSmsSaved(true);
      await refreshProfile();
    } catch (err) {
      setSmsError('Failed to save notification settings.');
    } finally {
      setSavingSms(false);
    }
  };

  const toggleLiveReferee = async () => {
    setSavingFeature(true);
    setFeatureError(null);
    try {
      await updateFeature('dice_live_referee', !liveReferee.opted_in);
    } catch (err) {
      setFeatureError('Failed to save beta preference.');
    } finally {
      setSavingFeature(false);
    }
  };

  if (profile === null) {
    return <div className="max-w-xl mx-auto px-4 sm:px-6 py-8">Loading…</div>;
  }

  return (
    <div className="max-w-xl mx-auto px-4 sm:px-6 py-8">
      <div className="jk-card p-6 sm:p-8 flex flex-col items-center text-center mb-6">
        <div className="relative mb-4">
          <PlayerAvatar profile={profile} size={104} linkToProfile={false} />
          {canEdit && (
            <label
              className="absolute -bottom-1 -right-1 flex items-center justify-center cursor-pointer"
              style={{
                width: 32,
                height: 32,
                borderRadius: '50%',
                background: 'var(--surface-strong)',
                color: 'var(--text-on-strong)',
                fontSize: 15,
                border: '2px solid var(--surface-card)',
              }}
              title="Change photo"
            >
              {uploading ? '…' : '✎'}
              <input type="file" accept="image/jpeg,image/png,image/webp" className="hidden" onChange={uploadAvatar} disabled={uploading} />
            </label>
          )}
        </div>
        <div className="w-full max-w-xs">
          {editing ? (
            <div className="flex items-center gap-2">
              <Input value={name} onChange={(e) => setName(e.target.value)} maxLength={60} />
              <Button size="sm" onClick={saveName} disabled={saving}>Save</Button>
              <Button size="sm" variant="ghost" onClick={() => { setEditing(false); setName(profile.display_name); }}>
                Cancel
              </Button>
            </div>
          ) : (
            <div className="flex items-center justify-center gap-2">
              <p className="jk-display truncate" style={{ fontSize: 26 }}>{profile.display_name}</p>
              {canEdit && (
                <button
                  type="button"
                  onClick={() => setEditing(true)}
                  className="flex-shrink-0"
                  style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-tertiary)' }}
                >
                  edit
                </button>
              )}
            </div>
          )}
          {error && <p style={{ color: 'var(--state-danger)', fontSize: 12 }} className="mt-1">{error}</p>}
        </div>
      </div>

      <div className="mb-8">
        <div className="grid grid-cols-2 sm:grid-cols-4 gap-3">
          <StatTile
            label="ELO"
            value={profile.elo_rating}
            badge={profile.is_provisional && <ProvisionalBadge gamesRemaining={profile.placement_games_remaining} />}
          />
          <StatTile label="Games" value={profile.games_played} />
          <StatTile label="Sinks" value={profile.sinks} />
          <StatTile label="Self Sinks" value={profile.self_sinks} />
        </div>
        <div className="grid grid-cols-2 gap-3 mt-3">
          <StatTile label="Ranked Record" value={`${profile.ranked_wins}-${profile.ranked_losses}`} />
          <StatTile label="Normal Record" value={`${profile.normal_wins}-${profile.normal_losses}`} />
        </div>
        {ratingProgress && (
          <div className="grid grid-cols-3 gap-3 mt-3" aria-label="Rating progress">
            <StatTile
              label="Rank"
              value={ratingProgress.current_rank
                ? `${ratingProgress.current_rank}`
                : ratingProgress.is_provisional ? 'Placing' : 'Hidden'}
            />
            <StatTile
              label="Last Match"
              value={ratingProgress.last_delta == null
                ? '—'
                : `${ratingProgress.last_delta >= 0 ? '+' : ''}${ratingProgress.last_delta}`}
            />
            <StatTile label="Personal Best" value={ratingProgress.personal_best} />
          </div>
        )}
        {ratingProgress?.last_rank_change != null && ratingProgress.last_rank_change !== 0 && (
          <p className="mt-2 text-center" role="status" style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--state-success)' }}>
            {ratingProgress.last_rank_change > 0
              ? `Moved up ${ratingProgress.last_rank_change} rank${ratingProgress.last_rank_change === 1 ? '' : 's'} last match.`
              : `Moved down ${Math.abs(ratingProgress.last_rank_change)} rank${ratingProgress.last_rank_change === -1 ? '' : 's'} last match.`}
          </p>
        )}
        {profile.is_provisional && (
          <p className="mt-2 text-center" style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-tertiary)' }}>
            {profile.placement_games_remaining} more ranked game{profile.placement_games_remaining === 1 ? '' : 's'} until this ELO is placed on the leaderboard.
          </p>
        )}
      </div>

      {!isOwnProfile && profile.head_to_head && (
        <div className="mb-8">
          <p className="jk-label mb-3">// HEAD TO HEAD</p>
          {profile.head_to_head.total_games === 0 ? (
            <div className="jk-card p-4 text-center text-sm" style={{ color: 'var(--text-tertiary)' }}>
              You haven't played any games with {profile.display_name} yet.
            </div>
          ) : (
            <div className="grid grid-cols-2 gap-3">
              <StatTile
                label="As Opponents"
                value={`${profile.head_to_head.opponent_wins}-${profile.head_to_head.opponent_losses}`}
              />
              <StatTile
                label="As Teammates"
                value={`${profile.head_to_head.teammate_wins}-${profile.head_to_head.teammate_losses}`}
              />
            </div>
          )}
        </div>
      )}

      <div className="mb-8">
        <p className="jk-label mb-3">// ELO HISTORY</p>
        <div className="jk-card p-4">
          {eloHistory === null && <p className="text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading…</p>}
          {eloHistory && eloHistory.length < 2 && (
            <p className="text-sm" style={{ color: 'var(--text-tertiary)' }}>
              Not enough ranked games yet to chart a trend.
            </p>
          )}
          {eloHistory && eloHistory.length >= 2 && <EloHistoryChart history={eloHistory} />}
        </div>
      </div>

      {canEdit && (
        <div className="mb-8">
          <p className="jk-label mb-3">// SETTINGS</p>
          <div className="jk-card p-4">
            <label className="flex items-center gap-2" style={{ fontFamily: 'var(--font-body)', fontSize: 14, color: 'var(--text-primary)' }}>
              <input
                type="checkbox"
                checked={profile.hide_from_leaderboard}
                onChange={toggleHideFromLeaderboard}
                disabled={savingSetting}
              />
              Hide my profile from leaderboard
            </label>
          </div>
        </div>
      )}

      {isOwnProfile && (
        <div className="mb-8">
          <p className="jk-label mb-3">// EXPERIMENTAL FEATURES</p>
          <div className="jk-card p-4">
            <label className="flex items-start gap-2" style={{ fontFamily: 'var(--font-body)', fontSize: 14, color: 'var(--text-primary)' }}>
              <input
                type="checkbox"
                checked={liveReferee.opted_in}
                onChange={toggleLiveReferee}
                disabled={savingFeature}
                className="mt-1"
              />
              <span>
                <span className="block font-medium">Live referee beta</span>
                <span className="block mt-1 text-xs" style={{ color: 'var(--text-tertiary)' }}>
                  Enables the new home, stats, and live referee.
                </span>
              </span>
            </label>
            {liveReferee.opted_in && (
              <p className="mt-3 text-xs" style={{ color: 'var(--state-success)' }}>Enabled for your account.</p>
            )}
            {featureError && <p className="mt-3 text-xs" style={{ color: 'var(--state-danger)' }}>{featureError}</p>}
          </div>
        </div>
      )}

      {isOwnProfile && (
        <div className="mb-8">
          <p className="jk-label mb-3">// NOTIFICATIONS</p>
          <div className="jk-card p-4">
            <label className="flex items-center gap-2" style={{ fontFamily: 'var(--font-body)', fontSize: 14, color: 'var(--text-primary)' }}>
              <input
                type="checkbox"
                checked={smsEnabled}
                onChange={(e) => setSmsEnabled(e.target.checked)}
                disabled={savingSms}
              />
              Text me every ranked game result
            </label>
            <div className="flex items-center gap-2 mt-3">
              <Input
                type="tel"
                value={phone}
                onChange={(e) => { setPhone(e.target.value); setSmsSaved(false); }}
                placeholder="(415) 555-1234"
                disabled={savingSms}
              />
              <Button size="sm" onClick={saveSmsSettings} disabled={savingSms}>
                {savingSms ? 'Saving…' : 'Save'}
              </Button>
            </div>
            {smsError && <p style={{ color: 'var(--state-danger)', fontSize: 12 }} className="mt-2">{smsError}</p>}
            {smsSaved && !smsError && <p style={{ color: 'var(--text-tertiary)', fontSize: 12 }} className="mt-2">Saved.</p>}
          </div>
        </div>
      )}

      <p className="jk-label mb-3">// GAME HISTORY</p>
      <div className="jk-card overflow-hidden">
        {games === null && <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>Loading…</p>}
        {games?.length === 0 && (
          <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>No games logged yet.</p>
        )}
        {games?.map((g) => (
          <GameRow
            key={g.id}
            game={g}
            perspectiveUserId={userId}
            ratingDelta={ratingProgress ? ratingDeltaByGame.get(g.id) ?? null : undefined}
          />
        ))}
      </div>

      {isOwnProfile && (
        <div className="flex justify-center mt-8">
          <Button size="sm" variant="ghost" onClick={signOut} className="flex items-center gap-2">
            <LogOut className="w-3.5 h-3.5" />
            Sign out
          </Button>
        </div>
      )}
    </div>
  );
}
