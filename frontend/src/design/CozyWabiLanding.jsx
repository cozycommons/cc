import React from 'react';
import { Link } from 'react-router-dom';
import '../../../design/cozy-wabi/styles.css';

function useBodyClass(className) {
  React.useEffect(() => {
    document.body.classList.add(className);
    return () => document.body.classList.remove(className);
  }, [className]);
}

function RoomArtwork() {
  return (
    <div className="room-wrap">
      <span className="room-wrap__annotation room-wrap__annotation--top" aria-hidden="true">demo room / evening, give or take</span>
      <span className="room-wrap__tape room-wrap__tape--one" aria-hidden="true" />
      <span className="room-wrap__tape room-wrap__tape--two" aria-hidden="true" />

      <article className="room" aria-label="A warmly lit common room with three resting residents, plants, and a listening nook.">
        <div className="room__light room__light--lamp" aria-hidden="true" />
        <div className="room__light room__light--window" aria-hidden="true" />
        <div className="room__wall" aria-hidden="true">
          <div className="window">
            <span className="window__moon" aria-hidden="true" />
            <span className="window__star window__star--one" aria-hidden="true">·</span>
            <span className="window__star window__star--two" aria-hidden="true">·</span>
            <span className="window__crossbar window__crossbar--vertical" aria-hidden="true" />
            <span className="window__crossbar window__crossbar--horizontal" aria-hidden="true" />
          </div>
          <div className="picture-frame" aria-hidden="true"><span /></div>
          <div className="wall-mark wall-mark--one" aria-hidden="true" />
          <div className="wall-mark wall-mark--two" aria-hidden="true" />
        </div>

        <div className="room__floor" aria-hidden="true">
          <span className="floor-line floor-line--one" />
          <span className="floor-line floor-line--two" />
          <span className="floor-line floor-line--three" />
        </div>

        <div className="room__window-seat" aria-hidden="true">
          <span className="window-seat__top" />
          <span className="window-seat__body" />
          <span className="window-seat__leg window-seat__leg--left" />
          <span className="window-seat__leg window-seat__leg--right" />
        </div>

        <div className="plant plant--tall" aria-hidden="true">
          <span className="plant__leaf plant__leaf--one" />
          <span className="plant__leaf plant__leaf--two" />
          <span className="plant__leaf plant__leaf--three" />
          <span className="plant__leaf plant__leaf--four" />
          <span className="plant__stem" />
          <span className="plant__pot" />
        </div>

        <div className="room__listening-nook" aria-hidden="true">
          <span className="sofa__back" />
          <span className="sofa__seat" />
          <span className="sofa__arm sofa__arm--left" />
          <span className="sofa__arm sofa__arm--right" />
          <span className="sofa__leg sofa__leg--left" />
          <span className="sofa__leg sofa__leg--right" />
          <span className="cushion cushion--one" />
          <span className="cushion cushion--two" />
        </div>

        <div className="rug" aria-hidden="true">
          <span className="rug__line rug__line--one" />
          <span className="rug__line rug__line--two" />
          <span className="rug__diamond">✦</span>
        </div>

        <div className="room__table" aria-hidden="true">
          <span className="table__top" />
          <span className="table__leg table__leg--left" />
          <span className="table__leg table__leg--right" />
          <span className="table__mug" />
          <span className="table__mug-handle" />
          <span className="table__book" />
        </div>

        <div className="room__figure room__figure--one" aria-hidden="true">
          <span className="figure__head" />
          <span className="figure__body" />
          <span className="figure__arm" />
        </div>
        <div className="room__figure room__figure--two" aria-hidden="true">
          <span className="figure__head" />
          <span className="figure__body" />
          <span className="figure__arm" />
        </div>
        <div className="room__figure room__figure--three" aria-hidden="true">
          <span className="figure__head" />
          <span className="figure__body" />
          <span className="figure__arm" />
        </div>

        <div className="room__sideboard" aria-hidden="true">
          <span className="sideboard__top" />
          <span className="sideboard__body" />
          <span className="sideboard__handle sideboard__handle--one" />
          <span className="sideboard__handle sideboard__handle--two" />
          <span className="sideboard__leg sideboard__leg--left" />
          <span className="sideboard__leg sideboard__leg--right" />
        </div>

        <div className="room__lamp" aria-hidden="true">
          <span className="lamp__shade" />
          <span className="lamp__stem" />
          <span className="lamp__base" />
        </div>

        <div className="room__status" aria-live="polite">
          <span className="room__status-dot" aria-hidden="true" />
          <span className="room__status-label">demo room / quiet</span>
          <span className="room__status-time">sample · 8:42 pm</span>
        </div>
      </article>

      <span className="room-wrap__annotation room-wrap__annotation--bottom" aria-hidden="true">three lamps / one good chair · demo</span>
    </div>
  );
}

export default function CozyWabiLanding() {
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [lampOn, setLampOn] = React.useState(false);
  useBodyClass('wabi-landing-body');

  React.useEffect(() => {
    document.body.classList.toggle('is-awake', lampOn);
    return () => document.body.classList.remove('is-awake');
  }, [lampOn]);

  return (
    <div className="wabi-landing">
      <div className="page-shell">
        <header className="masthead">
          <Link className="wordmark" to="/" aria-label="Cozy Commons home">
            <span className="wordmark__cozy">cozy</span>
            <span className="wordmark__commons">commons</span>
          </Link>

          <div className="masthead__right">
            <span className="edition-mark">a little home on the web</span>
            <nav className={`site-nav${menuOpen ? '' : ' is-collapsed'}`} id="site-navigation" aria-label="Primary navigation">
              <a href="#shelf">the shelf</a>
              <Link to="/design">common UI library</Link>
              <Link to="/dice">Dice ↗</Link>
            </nav>
            <button
              className="site-menu-toggle"
              type="button"
              aria-expanded={menuOpen}
              aria-controls="site-navigation"
              onClick={() => setMenuOpen((open) => !open)}
            >
              <span className="site-menu-toggle__label">{menuOpen ? 'close menu' : 'open menu'}</span>
            </button>
            <span className="sun-mark" aria-hidden="true">◌</span>
          </div>
        </header>

        <main id="top">
          <section className="hero" aria-labelledby="hero-title">
            <div className="hero__copy">
              <p className="eyebrow"><span className="eyebrow__dot" aria-hidden="true" /> common room / open quietly</p>
              <h1 id="hero-title">Make room<br /><em>for good things.</em></h1>
              <p className="hero__lede">Cozy Commons is a small, warm corner for the projects, rituals, and half-finished ideas we want to keep close.</p>

              <div className="hero__note">
                <span className="hero__note-line" aria-hidden="true" />
                <p>a small room<br />for things we make</p>
              </div>

              <a className="text-link" href="#shelf">
                <span>come in and look around</span>
                <span className="text-link__arrow" aria-hidden="true">↘</span>
              </a>
              <p className="hero__library-link"><Link to="/design">browse the common UI library ↗</Link></p>
            </div>

            <RoomArtwork />
          </section>

          <section className="shelf-section" id="shelf" aria-labelledby="shelf-title">
            <div className="section-heading">
              <div>
                <p className="eyebrow eyebrow--small"><span className="eyebrow__dot" aria-hidden="true" /> things on the shelf</p>
                <h2 id="shelf-title">A few things<br /><em>we keep returning to.</em></h2>
              </div>
              <p className="section-heading__aside">No grand archive.<br />Just the good bits.</p>
            </div>

            <div className="shelf" aria-label="Cozy Commons projects">
              <span className="shelf__backdrop" aria-hidden="true" />
              <span className="shelf__line shelf__line--top" aria-hidden="true" />
              <span className="shelf__line shelf__line--bottom" aria-hidden="true" />

              <Link className="project project--featured" to="/dice" aria-label="Open Dice beer die records and stats">
                <span className="project__index">01 / featured</span>
                <span className="project__icon" aria-hidden="true">
                  <span className="die-face die-face--one"><i /></span>
                </span>
                <span className="project__body">
                  <span className="project__name">Dice</span>
                  <span className="project__description">Beer die records, little rivalries,<br />and stats worth arguing about.</span>
                </span>
                <span className="project__arrow" aria-hidden="true">↗</span>
                <span className="project__caption">open the ledger</span>
              </Link>

              <div className="project project--waiting" aria-label="Second shelf slot, more soon">
                <span className="project__index">02 / waiting patiently</span>
                <span className="project__waiting-mark" aria-hidden="true">· · ·</span>
                <span className="project__body">
                  <span className="project__name">more soon</span>
                  <span className="project__description">There is room on the shelf<br />for the next small thing.</span>
                </span>
                <span className="project__caption">no rush</span>
              </div>
            </div>
          </section>
        </main>

        <footer className="footer">
          <p>made with a little patience <span aria-hidden="true">·</span> still becoming</p>
          <Link className="footer__library-link" to="/design">browse the common UI library ↗</Link>
          <button className="lamp-toggle" type="button" aria-pressed={lampOn} onClick={() => setLampOn((on) => !on)}>
            <span className="lamp-toggle__icon" aria-hidden="true">◒</span>
            <span className="lamp-toggle__label">{lampOn ? 'turn the light down' : 'leave a light on'}</span>
          </button>
        </footer>
      </div>
    </div>
  );
}
