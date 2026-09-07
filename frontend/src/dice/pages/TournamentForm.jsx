import React, { useEffect, useState } from 'react';
import { useNavigate, useParams } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { diceApi } from '../api.js';
import PlayerAvatar from '../components/PlayerAvatar.jsx';
import RosterPicker from '../components/RosterPicker.jsx';
import { canEditTournament } from '../utils.js';
import { easternWallTimeToUTC, utcToEasternWallTime } from '../timezone.js';

function HostPicker({ profiles, hosts, onChange }) {
  const addHost = (profile) => onChange([...hosts, profile]);
  const removeHost = (userId) => onChange(hosts.filter((h) => h.user_id !== userId));

  return (
    <div>
      <p className="jk-label mb-1">Hosts</p>
      {hosts.length > 0 && (
        <div className="flex flex-wrap gap-2 mb-2">
          {hosts.map((h) => (
            <div
              key={h.user_id}
              className="flex items-center gap-1.5 px-2 py-1"
              style={{ background: 'var(--surface-sunken)', borderRadius: 'var(--radius-pill)' }}
            >
              <PlayerAvatar profile={h} size={20} linkToProfile={false} />
              <span style={{ fontFamily: 'var(--font-body)', fontSize: 12 }}>{h.display_name}</span>
              <button
                type="button"
                onClick={() => removeHost(h.user_id)}
                style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-tertiary)' }}
              >
                ×
              </button>
            </div>
          ))}
        </div>
      )}
      <RosterPicker
        profiles={profiles}
        excludeIds={hosts.map((h) => h.user_id)}
        onPick={addHost}
        allTakenMessage="Everyone has already been added as a host."
      />
    </div>
  );
}

export default function TournamentForm({ auth, editMode = false }) {
  const { tournamentId } = useParams();
  const navigate = useNavigate();
  const { user, token, isAdmin, loading: authLoading } = auth;

  const [profiles, setProfiles] = useState(null);
  const [name, setName] = useState('');
  const [startsAt, setStartsAt] = useState('');
  const [description, setDescription] = useState('');
  const [hosts, setHosts] = useState([]);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState(null);
  const [loadingTournament, setLoadingTournament] = useState(editMode);
  const [canEdit, setCanEdit] = useState(!editMode);

  useEffect(() => {
    diceApi.searchProfiles('', 100).then(setProfiles).catch((err) => {
      console.error('Failed to load players for the host picker:', err);
      setProfiles([]);
    });
  }, []);

  useEffect(() => {
    if (!editMode) return;
    diceApi.getTournament(tournamentId).then((t) => {
      setName(t.name);
      setStartsAt(utcToEasternWallTime(t.starts_at));
      setDescription(t.description || '');
      setHosts(t.hosts);
      setCanEdit(canEditTournament(t, user, isAdmin));
      setLoadingTournament(false);
    }).catch((err) => {
      console.error('Failed to load tournament for editing:', err);
      setLoadingTournament(false);
    });
  }, [editMode, tournamentId, user, isAdmin]);

  const canSubmit = name.trim() && startsAt && !submitting;

  const handleSubmit = async (e) => {
    e.preventDefault();
    if (!canSubmit || !token) return;
    setSubmitting(true);
    setError(null);
    try {
      const payload = {
        name: name.trim(),
        starts_at: easternWallTimeToUTC(startsAt),
        host_user_ids: hosts.map((h) => h.user_id),
        description: description.trim(),
      };
      if (editMode) {
        await diceApi.updateTournament(token, tournamentId, payload);
        navigate(`/dice/tournament/${tournamentId}`);
      } else {
        const created = await diceApi.createTournament(token, payload);
        navigate(`/dice/tournament/${created.id}`);
      }
    } catch (err) {
      setError('Failed to save tournament.');
    } finally {
      setSubmitting(false);
    }
  };

  if (authLoading || loadingTournament) {
    return <div className="max-w-xl mx-auto px-4 sm:px-6 py-8">Loading…</div>;
  }

  if (!user || (!isAdmin && !editMode)) {
    return (
      <div className="max-w-xl mx-auto px-4 sm:px-6 py-8">
        <p style={{ color: 'var(--text-secondary)' }}>Only an admin can create a tournament.</p>
      </div>
    );
  }

  if (editMode && !canEdit) {
    return (
      <div className="max-w-xl mx-auto px-4 sm:px-6 py-8">
        <p style={{ color: 'var(--text-secondary)' }}>Only a host or an admin can edit this tournament.</p>
      </div>
    );
  }

  return (
    <div className="max-w-xl mx-auto px-4 sm:px-6 py-8">
      <p className="jk-display mb-6" style={{ fontSize: 28 }}>{editMode ? 'Edit Tournament' : 'New Tournament'}</p>
      <form onSubmit={handleSubmit} className="jk-card p-6 flex flex-col gap-6">
        <div>
          <p className="jk-label mb-1">Name</p>
          <Input value={name} onChange={(e) => setName(e.target.value)} placeholder="Summer Bash" required />
        </div>

        <div>
          <p className="jk-label mb-1">Date &amp; Time</p>
          <Input type="datetime-local" value={startsAt} onChange={(e) => setStartsAt(e.target.value)} required />
        </div>

        <div>
          <p className="jk-label mb-1">Description</p>
          <Textarea
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Format, prizes, links to sign-up sheets…"
            rows={4}
          />
        </div>

        <HostPicker profiles={profiles} hosts={hosts} onChange={setHosts} />

        {error && <p style={{ color: 'var(--state-danger)', fontSize: 13 }}>{error}</p>}

        <Button type="submit" disabled={!canSubmit} style={{ background: 'var(--accent-primary)', color: '#fff' }}>
          {submitting ? 'Saving…' : editMode ? 'Save Changes' : 'Create Tournament'}
        </Button>
      </form>
    </div>
  );
}
