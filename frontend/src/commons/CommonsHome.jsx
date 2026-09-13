import React from 'react';
import { Link } from 'react-router-dom';
import './commons-home.css';

export default function CommonsHome() {
  return (
    <main className="commons-home">
      <div className="commons-home__grain" aria-hidden="true" />

      <section className="commons-home__card" aria-labelledby="commons-home-title">
        <p className="commons-home__eyebrow">cozy commons</p>
        <h1 id="commons-home-title">A small room for things we make.</h1>
        <p className="commons-home__description">
          Start with Dice, a record of beer die games and stats.
        </p>

        <Link className="commons-home__project" to="/dice">
          <span className="commons-home__project-copy">
            <span className="commons-home__project-label">01 · project</span>
            <span className="commons-home__project-name">Dice</span>
            <span className="commons-home__project-description">beer die records and stats</span>
          </span>
          <span className="commons-home__project-arrow" aria-hidden="true">↗</span>
        </Link>
      </section>
    </main>
  );
}
