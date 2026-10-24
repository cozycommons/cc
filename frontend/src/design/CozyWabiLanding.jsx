import React from 'react';
import { Link } from 'react-router-dom';
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
          </div>
        </section>
      </main>
    </div>
  );
}
