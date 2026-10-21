import React from 'react';
import { Link } from 'react-router-dom';
import { Dice3, Music2 } from 'lucide-react';
import '../../../design/cozy-wabi/components.css';
import './cozy-home.css';

export default function CozyWabiLanding() {
  React.useEffect(() => {
    document.body.classList.add('commons-home-body');
    return () => document.body.classList.remove('commons-home-body');
  }, []);

  return (
    <div className="cc-page commons-home">
      <header className="cc-navbar">
        <Link className="cc-brand" to="/" aria-label="Cozy Commons home">
          <span className="cc-brand__cozy">cozy</span>
          <span className="cc-brand__commons">commons</span>
        </Link>
      </header>

      <main>
        <section className="cc-home-shelf" id="shelf" aria-labelledby="shelf-title">
          <h1 id="shelf-title">The shelf</h1>
          <div className="cc-home-shelf__projects">
            <Link className="cc-card cc-card--interactive cc-home-project" to="/dice" aria-label="Open Dice beer die records and stats">
              <Dice3 className="cc-home-project__icon" size={32} strokeWidth={1.5} aria-hidden="true" />
              <h2 className="cc-h3">Dice</h2>
              <p className="cc-body">Beer die records and stats.</p>
              <span className="cc-card__arrow" aria-hidden="true">↗</span>
            </Link>
            <Link className="cc-card cc-card--interactive cc-home-project" to="/crowdset" aria-label="Open Crowdset concert videos">
              <Music2 className="cc-home-project__icon" size={32} strokeWidth={1.5} aria-hidden="true" />
              <h2 className="cc-h3">Crowdset</h2>
              <p className="cc-body">Shared concert videos.</p>
              <span className="cc-card__arrow" aria-hidden="true">↗</span>
            </Link>
          </div>
        </section>
      </main>
    </div>
  );
}
