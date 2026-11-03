import React from 'react';
import { Link, useLocation, useNavigate } from 'react-router-dom';
import { ArrowLeft, BarChart3, Plus, Users } from 'lucide-react';
import { Button } from '@/components/ui/button';
import PlayerAvatar from './components/PlayerAvatar.jsx';
import SiteHeader from '../components/SiteHeader.jsx';
import { diceParentPath, isDiceHome } from './diceBack.js';

// Steps back through in-app history (including Stats tabs). With no earlier
// in-app page, e.g. a shared link, it goes to the page's parent instead of
// leaving the site.
function DiceBackButton() {
  const navigate = useNavigate();
  const location = useLocation();
  if (isDiceHome(location.pathname)) return null;
  const goBack = () => {
    // BrowserRouter records each entry's position in history.state.idx (0 for
    // the first page of this visit, and still 0 after a replace).
    const index = window.history.state?.idx;
    const hasInAppHistory = typeof index === 'number' ? index > 0 : location.key !== 'default';
    if (hasInAppHistory) navigate(-1);
    else navigate(diceParentPath(location.pathname, location.search), { replace: true });
  };
  return (
    <button type="button" className="cc-sitebar-icon jk-dice-back" onClick={goBack} aria-label="Back" title="Back">
      <ArrowLeft className="w-5 h-5" aria-hidden="true" />
    </button>
  );
}

export default function DiceHeader({ auth }) {
  const { user, profile, loading, signIn } = auth;
  const navigate = useNavigate();
  const isSandbox = import.meta.env.VITE_DICE_LOCAL_HARNESS === 'true';

  return (
    <div
      className="jk-dice-header w-full px-4 sm:px-6 py-3"
      style={{ background: 'var(--surface-page)' }}
    >
      <SiteHeader product="Dice" to="/dice" icon="🎲" leading={<DiceBackButton />}>
        {isSandbox && (
          <span
            className="jk-label px-2 py-1 rounded-full"
            style={{ background: 'var(--accent-gold)', color: 'var(--ink-950)' }}
            title="Synthetic data in an isolated development environment"
          >
            Private sandbox
          </span>
        )}

      <div className="jk-dice-header-actions flex items-center gap-2 flex-wrap justify-end">
        <Button size="sm" variant="outline" onClick={() => navigate('/dice/leaderboard/elo')} aria-label="Players">
          <Users className="w-4 h-4" />
          <span className="hidden sm:inline">Players</span>
        </Button>

        <Button size="sm" variant="outline" onClick={() => navigate('/dice/stats')} aria-label="Stats">
          <BarChart3 className="w-4 h-4" />
          <span className="hidden sm:inline">Stats</span>
        </Button>

        <Button
          size="sm"
          onClick={() => (user ? navigate('/dice/live') : signIn())}
          style={{ background: 'var(--accent-primary)', color: '#fff' }}
        >
          <Plus className="w-4 h-4" />
          Start Match
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
      </SiteHeader>
    </div>
  );
}
