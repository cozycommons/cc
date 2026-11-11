import React from 'react';
import { Link } from 'react-router-dom';
import '../../../design/cozy-wabi/components.css';
import './cozy-home.css';
import { Bike, Sparkles } from 'lucide-react';
import { useCommonsIdentity } from '../components/commonsIdentity.js';
import { getUrl } from '../api.js';
import SiteHeader from '../components/SiteHeader.jsx';

export default function CozyWabiLanding() {
  const { status, user } = useCommonsIdentity();
  const [catalog, setCatalog] = React.useState(null);
  const apps = status === 'signed-in' && catalog?.userId === user?.id ? catalog.apps : [];
  React.useEffect(() => {
    setCatalog(null);
    if (status !== 'signed-in') return undefined;
    const controller = new AbortController();
    (async () => {
      const { getClient } = await import('../supabase.js');
      const { data } = await getClient().auth.getSession();
      if (!data?.session?.access_token || data.session.user?.id !== user.id || controller.signal.aborted) return;
      const response = await fetch(`${getUrl()}/apps/catalog`, {
        headers: { Authorization: `Bearer ${data.session.access_token}` },
        signal: controller.signal, cache: 'no-store',
      });
      if (!response.ok) throw new Error('Apps unavailable');
      const catalog = await response.json();
      if (!controller.signal.aborted) setCatalog({ userId: user.id, apps: catalog });
    })().catch(() => {});
    return () => controller.abort();
  }, [status, user?.id]);
  React.useEffect(() => {
    document.body.classList.add('commons-home-body');
    return () => document.body.classList.remove('commons-home-body');
  }, []);

  return (
    <div className="cc-page commons-home">
      <SiteHeader />

      <main>
        <section className="cc-home-shelf" id="shelf" aria-label="Projects">
          <div className="cc-home-shelf__projects">
            <span className="cc-home-shelf__backdrop" aria-hidden="true" />
            <span className="cc-home-shelf__line cc-home-shelf__line--top" aria-hidden="true" />
            <span className="cc-home-shelf__line cc-home-shelf__line--bottom" aria-hidden="true" />
            <Link className="cc-home-project" to="/dice" aria-label="Open Dice beer die records and stats">
              <span className="cc-home-project__icon" aria-hidden="true">
                <span className="cc-home-die"><i /></span>
              </span>
              <div className="cc-home-project__body">
                <h2>Dice</h2>
                <p>Beer die records and stats.</p>
              </div>
              <span className="cc-home-project__arrow" aria-hidden="true">↗</span>
            </Link>
            <Link className="cc-home-project cc-home-project--crowdset" to="/crowdset" aria-label="Open Crowdset concert videos">
              <span className="cc-home-project__icon" aria-hidden="true">♫</span>
              <div className="cc-home-project__body">
                <h2>Crowdset</h2>
                <p>Shared concert videos.</p>
              </div>
              <span className="cc-home-project__arrow" aria-hidden="true">↗</span>
            </Link>
            <Link className="cc-home-project" to="/fantasy" aria-label="Open fantasy basketball predictions">
              <span className="cc-home-project__icon" aria-hidden="true">◎</span>
              <div className="cc-home-project__body">
                <h2>Fantasy</h2>
                <p>League predictions, updated daily.</p>
              </div>
              <span className="cc-home-project__arrow" aria-hidden="true">↗</span>
            </Link>
            <Link className="cc-home-project" to="/trips" aria-label="Open Cozy Trips shared trip expenses">
              <span className="cc-home-project__icon" aria-hidden="true">↗</span>
              <div className="cc-home-project__body">
                <h2>Cozy Trips</h2>
                <p>Good trips. Clear tabs.</p>
              </div>
              <span className="cc-home-project__arrow" aria-hidden="true">↗</span>
            </Link>
            <Link className="cc-home-project" to="/bikes" aria-label="Open Cozy Bikes live Citi Bike stations">
              <span className="cc-home-project__icon" aria-hidden="true"><Bike size={26} strokeWidth={1.8} /></span>
              <div className="cc-home-project__body">
                <h2>Bikes</h2>
                <p>A Citi Bike or a dock, and the odds when you arrive.</p>
              </div>
              <span className="cc-home-project__arrow" aria-hidden="true">↗</span>
            </Link>
            <Link className="cc-home-project" to="/vital" aria-label="Open VITAL Brooklyn live headcount">
              <span className="cc-home-project__icon" aria-hidden="true">🧗</span>
              <div className="cc-home-project__body">
                <h2>VITAL</h2>
                <p>How busy the Brooklyn gym is now, and when it's quiet.</p>
              </div>
              <span className="cc-home-project__arrow" aria-hidden="true">↗</span>
            </Link>
            <Link className="cc-home-project" to="/floor-planner" aria-label="Open Cozy Floor Planner">
              <span className="cc-home-project__icon" aria-hidden="true">⌑</span>
              <div className="cc-home-project__body">
                <h2>Floor Planner</h2>
                <p>Measured room plans, shared by email.</p>
              </div>
              <span className="cc-home-project__arrow" aria-hidden="true">↗</span>
            </Link>
            {apps.map((app) => (
              <a key={app.name} className="cc-home-project cc-home-project--app" href={app.url}>
                <span className="cc-home-project__icon" aria-hidden="true"><Sparkles size={26} strokeWidth={1.8} /></span>
                <div className="cc-home-project__body">
                  <h2>{app.name.split('-').map((word) => word.charAt(0).toUpperCase() + word.slice(1)).join(' ')} <span className="cc-home-app-badge">App</span></h2>
                  <p>{app.status === 'running' ? 'Open app' : 'Currently stopped'}</p>
                </div>
                <span className="cc-home-project__arrow" aria-hidden="true">↗</span>
              </a>
            ))}
          </div>
        </section>
      </main>
    </div>
  );
}
