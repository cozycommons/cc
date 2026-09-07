import React from 'react';
import { Link, useNavigate } from 'react-router-dom';
import { BarChart3, Plus, Users } from 'lucide-react';
import { Button } from '@/components/ui/button';
import PlayerAvatar from './components/PlayerAvatar.jsx';

export default function DiceHeader({ auth }) {
  const { user, profile, loading, signIn } = auth;
  const navigate = useNavigate();
  const isSandbox = import.meta.env.VITE_DICE_LOCAL_HARNESS === 'true';
  const liveEnabled = auth.features?.dice_live_referee?.effective === true;

  return (
    <nav
      className="w-full px-4 sm:px-6 py-3 flex items-center justify-between flex-wrap gap-y-2"
      style={{ borderBottom: '1px solid var(--border-subtle)', background: 'var(--surface-page)' }}
    >
      <div className="flex items-center gap-4 flex-shrink-0">
        <Link
          to="/dice"
          className="jk-display whitespace-nowrap"
          style={{ fontSize: 22, color: 'var(--text-primary)' }}
        >
          🎲 Dice
        </Link>
        {isSandbox && (
          <span
            className="jk-label px-2 py-1 rounded-full"
            style={{ background: 'var(--accent-gold)', color: 'var(--ink-950)' }}
            title="Synthetic data in an isolated development environment"
          >
            Private sandbox
          </span>
        )}
      </div>

      <div className="flex items-center gap-2 flex-wrap justify-end">
        <Button size="sm" variant="outline" onClick={() => navigate('/dice/players')} aria-label="Players">
          <Users className="w-4 h-4" />
          <span className="hidden sm:inline">Players</span>
        </Button>

        {liveEnabled && (
          <Button size="sm" variant="outline" onClick={() => navigate('/dice/stats')} aria-label="Stats">
            <BarChart3 className="w-4 h-4" />
            <span className="hidden sm:inline">Stats</span>
          </Button>
        )}

        <Button
          size="sm"
          onClick={() => (user ? navigate(liveEnabled ? '/dice/live' : '/dice/log') : signIn())}
          style={{ background: 'var(--accent-primary)', color: '#fff' }}
        >
          <Plus className="w-4 h-4" />
          {liveEnabled ? 'Start Match' : 'Log Match'}
        </Button>

        {!loading && (
          user ? (
            <Link to={`/dice/profile/${user.id}`} className="block rounded-full" aria-label="My profile">
              <PlayerAvatar profile={profile} size={32} linkToProfile={false} />
            </Link>
          ) : (
            <Button size="sm" variant="outline" onClick={signIn}>
              Sign in
            </Button>
          )
        )}
      </div>
    </nav>
  );
}
