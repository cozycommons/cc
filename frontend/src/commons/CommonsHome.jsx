import React from 'react';
import { Link } from 'react-router-dom';
import CommonsScene from './CommonsScene.jsx';
import './commons-theme.css';

export default function CommonsHome() {
  return (
    <main className="commons-home">
      <div className="commons-home__grain" aria-hidden="true" />

      <header className="commons-home__header">
        <Link className="commons-home__wordmark" to="/" aria-label="Cozy Commons home">
          <span>cozy</span>
          <span>commons</span>
        </Link>

        <p className="commons-home__quiet-note">a small room for things we make</p>
      </header>

      <section className="commons-room" aria-label="The Cozy Commons room">
        <CommonsScene />
      </section>

      <aside className="commons-shelf" aria-labelledby="commons-shelf-title">
        <div className="commons-shelf__header">
          <span className="commons-label" id="commons-shelf-title">projects</span>
          <span className="commons-shelf__mark" aria-hidden="true">✦</span>
        </div>

        <Link className="commons-project commons-project--active" to="/dice">
          <span className="commons-project__number">01</span>
          <span className="commons-project__name">Dice</span>
          <span className="commons-project__arrow" aria-hidden="true">↗</span>
          <span className="commons-project__description">beer die records<br />and stats</span>
        </Link>

        <div className="commons-project commons-project--soon" aria-label="More projects coming soon">
          <span className="commons-project__number">02</span>
          <span className="commons-project__name">more soon</span>
          <span className="commons-project__description">there is room<br />on the shelf</span>
        </div>
      </aside>

      <div className="commons-home__footer" aria-hidden="true">
        <span className="commons-home__status-dot" />
        <span>the room is quiet</span>
      </div>
    </main>
  );
}
