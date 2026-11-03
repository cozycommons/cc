import React from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';
import { diceApi } from '../api.js';
import { useDiceResource } from '../resourceCache.js';
import TournamentRow from '../components/TournamentRow.jsx';
import LoadingRows from '../components/LoadingRows.jsx';

export default function Tournaments({ auth }) {
  const [tournaments] = useDiceResource('tournaments:200', () => diceApi.getTournaments(200), { fallback: [] });
  const { isAdmin } = auth || {};

  return (
    <div className="max-w-2xl mx-auto px-4 sm:px-6 py-8">
      <div className="flex items-center justify-between mb-4">
        <p className="jk-display" style={{ fontSize: 28 }}>Tournaments</p>
        {isAdmin && (
          <Link to="/dice/tournament/new">
            <Button size="sm" style={{ background: 'var(--accent-primary)', color: '#fff' }}>
              New Tournament
            </Button>
          </Link>
        )}
      </div>
      <div className="jk-card overflow-hidden">
        {tournaments === null && <LoadingRows />}
        {tournaments?.length === 0 && (
          <p className="p-4 text-sm" style={{ color: 'var(--text-tertiary)' }}>No tournaments yet.</p>
        )}
        {tournaments?.map((t) => <TournamentRow key={t.id} tournament={t} />)}
      </div>
    </div>
  );
}
