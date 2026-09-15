import React from 'react';
import { Link } from 'react-router-dom';
import '../../../design/cozy-wabi/components.css';

function useBodyClass(className) {
  React.useEffect(() => {
    document.body.classList.add(className);
    return () => document.body.classList.remove(className);
  }, [className]);
}

function Kicker({ children }) {
  return <p className="cc-kicker"><span className="cc-kicker__dot" aria-hidden="true" /> {children}</p>;
}

function SectionHeading({ eyebrow, title, aside, id, compact = false }) {
  return (
    <div className={`cc-section-heading${compact ? ' cc-section-heading--compact' : ''}`}>
      <div>
        <Kicker>{eyebrow}</Kicker>
        <h2 className="cc-h2" id={id}>{title}</h2>
      </div>
      {aside && <p className="cc-section-heading__aside">{aside}</p>}
    </div>
  );
}

function DemoForm({ showToast }) {
  const [errors, setErrors] = React.useState({});
  const [status, setStatus] = React.useState('');
  const nameRef = React.useRef(null);
  const emailRef = React.useRef(null);
  const kindRef = React.useRef(null);
  const rememberRef = React.useRef(null);

  const submit = (event) => {
    event.preventDefault();
    const nextErrors = {};
    const name = nameRef.current;
    const email = emailRef.current;
    const kind = kindRef.current;
    const remember = rememberRef.current;

    if (!name.value.trim()) nextErrors.name = 'Add a name before continuing.';
    if (!email.value.trim() || !email.validity.valid) nextErrors.email = 'Use an email like hello@example.com.';
    if (!kind.value) nextErrors.kind = 'Choose one small record type.';
    if (!remember.checked) nextErrors.remember = 'Check this before continuing.';

    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) {
      setStatus('A few small details need your attention.');
      const firstInvalid = [name, email, kind, remember].find((control) => {
        const field = control === remember ? 'remember' : control.name;
        return nextErrors[field];
      });
      firstInvalid?.focus();
      return;
    }

    setStatus('Confirmed locally — demo record ready; nothing was sent.');
    showToast('Saved locally — nothing was sent.');
  };

  const clearError = (key) => {
    if (!errors[key]) return;
    setErrors((current) => {
      const next = { ...current };
      delete next[key];
      return next;
    });
  };

  return (
    <form className="cc-form" onSubmit={submit} noValidate>
      <div className="cc-form__grid">
        <div className={`cc-field${errors.name ? ' cc-field--error' : ''}`}>
          <label className="cc-label" htmlFor="record-name">your name <span className="cc-field__required">required</span></label>
          <input className="cc-input" id="record-name" name="name" type="text" autoComplete="name" required aria-invalid={Boolean(errors.name)} aria-describedby="record-name-help" ref={nameRef} onInput={() => clearError('name')} />
          <p className="cc-help" id="record-name-help">A local sample player name.</p>
          {errors.name && <p className="cc-field__error" role="alert">{errors.name}</p>}
        </div>
        <div className={`cc-field${errors.email ? ' cc-field--error' : ''}`}>
          <label className="cc-label" htmlFor="record-email">email <span className="cc-field__required">required</span></label>
          <input className="cc-input" id="record-email" name="email" type="email" autoComplete="email" required aria-invalid={Boolean(errors.email)} ref={emailRef} onInput={() => clearError('email')} />
          {errors.email && <p className="cc-field__error" role="alert">{errors.email}</p>}
        </div>
        <div className="cc-field">
          <label className="cc-label" htmlFor="record-search">search records</label>
          <input className="cc-input" id="record-search" name="search" type="search" placeholder="e.g. patio rematch" />
        </div>
        <div className={`cc-field${errors.kind ? ' cc-field--error' : ''}`}>
          <label className="cc-label" htmlFor="record-kind">record type <span className="cc-field__required">required</span></label>
          <select className="cc-select" id="record-kind" name="kind" required aria-invalid={Boolean(errors.kind)} ref={kindRef} onChange={() => clearError('kind')}>
            <option value="">Choose a type</option>
            <option value="round">round</option>
            <option value="rematch">rematch</option>
            <option value="tournament">tiny tournament</option>
          </select>
          {errors.kind && <p className="cc-field__error" role="alert">{errors.kind}</p>}
        </div>
      </div>

      <div className="cc-field">
        <label className="cc-label" htmlFor="record-note">field note</label>
        <textarea className="cc-textarea" id="record-note" name="note" rows="4" placeholder="What is worth remembering?" />
      </div>

      <fieldset className="cc-fieldset">
        <legend className="cc-label">record mood</legend>
        <div className="cc-choice-row">
          <label className="cc-choice"><input type="radio" name="mood" value="steady" defaultChecked /> steady</label>
          <label className="cc-choice"><input type="radio" name="mood" value="lively" /> lively</label>
          <label className="cc-choice"><input type="radio" name="mood" value="legendary" /> legendary</label>
        </div>
      </fieldset>

      <div className="cc-form__split">
        <label className="cc-switch">
          <input id="record-reminder" name="reminder" type="checkbox" role="switch" defaultChecked />
          <span className="cc-switch__track" aria-hidden="true"><span className="cc-switch__thumb" /></span>
          <span className="cc-label">keep a local reminder</span>
        </label>
        <div className="cc-range-field">
          <label className="cc-label" htmlFor="record-warmth">paper warmth <output id="record-warmth-output" htmlFor="record-warmth">68%</output></label>
          <input className="cc-range" id="record-warmth" name="warmth" type="range" min="0" max="100" defaultValue="68" />
        </div>
      </div>

      <label className={`cc-choice cc-choice--consent${errors.remember ? ' cc-field--error' : ''}`}>
        <input id="record-remember" name="remember" type="checkbox" required ref={rememberRef} onChange={() => clearError('remember')} />
        I understand this is demo data.
      </label>
      {errors.remember && <p className="cc-field__error" role="alert">{errors.remember}</p>}
      <div className="cc-form__actions">
        <button className="cc-button cc-button--primary" type="submit">confirm locally <span aria-hidden="true">↗</span></button>
        <p className={`cc-form__status${status.startsWith('Confirmed') ? ' is-success' : status ? ' is-error' : ''}`} role="status" aria-live="polite">{status}</p>
      </div>
    </form>
  );
}

export default function DesignIndex() {
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [activeTab, setActiveTab] = React.useState('room');
  const [toast, setToast] = React.useState(null);
  const [dialogOpen, setDialogOpen] = React.useState(false);
  const dialogRef = React.useRef(null);
  const toastTimer = React.useRef(null);
  useBodyClass('cc-components-body');

  const showToast = (message) => {
    window.clearTimeout(toastTimer.current);
    setToast(message);
    toastTimer.current = window.setTimeout(() => setToast(null), 4200);
  };

  React.useEffect(() => () => window.clearTimeout(toastTimer.current), []);

  React.useEffect(() => {
    if (dialogOpen) dialogRef.current?.querySelector('button')?.focus();
  }, [dialogOpen]);

  const openDialog = () => {
    const dialog = dialogRef.current;
    if (typeof dialog?.showModal === 'function') dialog.showModal();
    else dialog?.setAttribute('open', '');
    setDialogOpen(true);
  };

  const closeDialog = () => {
    const dialog = dialogRef.current;
    if (typeof dialog?.close === 'function' && dialog.open) dialog.close();
    else dialog?.removeAttribute('open');
    setDialogOpen(false);
  };

  const tabs = [
    { id: 'room', label: 'room notes', eyebrow: 'demo room', title: 'The lamp is a local pool of amber.', body: 'Nothing here claims to be live. It is a composed little room for seeing how a surface might feel.' },
    { id: 'records', label: 'records', eyebrow: 'sample stats', title: 'Dice keeps the friendly arguments.', body: <>Demo record: patio rematch / 3 rounds / 2 players. The actual app lives at <Link className="cc-inline-link" to="/dice">/dice</Link>.</> },
    { id: 'rituals', label: 'rituals', eyebrow: 'quiet ritual', title: 'Open, notice, leave a light on.', body: 'A tab is useful when the content changes but the place stays familiar.' },
  ];
  const activePanel = tabs.find((tab) => tab.id === activeTab) || tabs[0];

  return (
    <div className="cc-page">
      <header className="cc-navbar">
        <Link className="cc-brand" to="/" aria-label="Return to Cozy Commons room">
          <span className="cc-brand__cozy">cozy</span>
          <span className="cc-brand__commons">commons / common UI</span>
        </Link>

        <p className="cc-navbar__note">living system / no live data</p>
        <button className="cc-menu-toggle" type="button" aria-expanded={menuOpen} aria-controls="cc-site-navigation" onClick={() => setMenuOpen((open) => !open)}>
          <span className="cc-menu-toggle__label">{menuOpen ? 'close menu' : 'open menu'}</span>
        </button>
        <nav className={`cc-navbar__links${menuOpen ? '' : ' is-collapsed'}`} id="cc-site-navigation" aria-label="Component library navigation">
          <Link to="/">landing room</Link>
          <a href="#buttons">inventory</a>
          <Link to="/dice">Dice ↗</Link>
        </nav>
      </header>

      <main>
        <section className="cc-hero" aria-labelledby="library-title">
          <div className="cc-hero__copy">
            <Kicker>common room / reusable pieces</Kicker>
            <h1 className="cc-display" id="library-title">A small kit<br /><em>close at hand.</em></h1>
            <p className="cc-lead">The chosen Wabi direction, carried into a living kit of tactile controls, paper surfaces, and quiet local interactions.</p>
            <div className="cc-hero__actions"><a className="cc-button cc-button--primary" href="#buttons">browse inventory <span aria-hidden="true">↘</span></a><Link className="cc-button cc-button--ghost" to="/">back to the room</Link></div>
          </div>
        </section>

        <div className="cc-inventory-bar" aria-label="Specimen inventory">
          <span>01 actions</span><span>02 surfaces</span><span>03 type</span><span>04 controls</span><span>05 feedback</span><span>06 overlays</span>
          <span className="cc-inventory-bar__palette">warm washi · iron glaze · burnt sienna · local amber</span>
        </div>

        <section className="cc-section" id="buttons" aria-labelledby="buttons-title">
          <SectionHeading compact eyebrow="01 / actions" id="buttons-title" title={<>Raised keys<br /><em>with a soft landing.</em></>} aside={<>Hover, focus, press,<br />disabled, and loading.</>} />
          <div className="cc-plate cc-action-plate"><div className="cc-button-row" aria-label="Button variants"><button className="cc-button cc-button--primary" type="button" onClick={() => showToast('Primary action acknowledged.')}>primary</button><button className="cc-button cc-button--secondary" type="button" onClick={() => showToast('Secondary action acknowledged.')}>secondary</button><button className="cc-button cc-button--ghost" type="button">ghost</button><button className="cc-button cc-button--destructive" type="button">destructive</button><button className="cc-button cc-button--secondary cc-button--icon" type="button" aria-label="Add a sample record" title="Add a sample record" onClick={() => showToast('Add record is local.')}>+</button><button className="cc-button cc-button--primary cc-button--small" type="button">small</button><button className="cc-button cc-button--secondary cc-button--active" type="button" aria-pressed="true">active</button><button className="cc-button cc-button--primary" type="button" disabled>disabled</button><button className="cc-button cc-button--primary cc-button--loading" type="button" aria-busy="true" disabled><span className="cc-spinner" aria-hidden="true" />loading</button></div><p className="cc-caption">Every action keeps a 44px minimum target. The pressed sample is a static state; the loading sample is intentionally local.</p></div>
        </section>

        <section className="cc-section" id="cards" aria-labelledby="cards-title">
          <SectionHeading compact eyebrow="02 / surfaces" id="cards-title" title={<>Four ways to<br /><em>hold a thought.</em></>} aside={<>Different materials,<br />different jobs.</>} />
          <div className="cc-card-grid">
            <article className="cc-card cc-card--elevated"><p className="cc-label">elevated card</p><h3 className="cc-h3">A little lift</h3><p className="cc-body">For an item that needs to sit forward from the page.</p><span className="cc-card__rule" aria-hidden="true" /><span className="cc-caption">paper / low shadow</span></article>
            <article className="cc-card cc-card--inset"><p className="cc-label">inset card</p><h3 className="cc-h3">A quiet well</h3><p className="cc-body">For grouped settings and details that belong together.</p><span className="cc-card__rule" aria-hidden="true" /><span className="cc-caption">recessed / close at hand</span></article>
            <button className="cc-card cc-card--interactive" type="button" onClick={() => showToast('Interactive card acknowledged.')}><span className="cc-label">interactive card</span><span className="cc-h3">Touch the edge</span><span className="cc-body">A card can carry a whole action when the affordance is clear.</span><span className="cc-card__arrow" aria-hidden="true">↗</span></button>
            <Link className="cc-card cc-card--project" to="/dice" aria-label="Open Dice beer die records and stats"><span className="cc-badge cc-badge--accent">live route</span><span className="cc-card__project-icon" aria-hidden="true"><span>1</span></span><span className="cc-label">project card / 01</span><span className="cc-h3">Dice</span><span className="cc-body">Beer die records, rivalries, and stats worth arguing about.</span><span className="cc-caption">open / sample records</span></Link>
          </div>
          <p className="cc-note"><span className="cc-badge cc-badge--demo">route note</span> The Dice card opens the working app at <code>/dice</code>.</p>
        </section>

        <section className="cc-section cc-section--type" id="typography" aria-labelledby="typography-title">
          <SectionHeading compact eyebrow="03 / typography" id="typography-title" title={<>A modest voice<br /><em>with room to breathe.</em></>} aside={<>Editorial serif for feeling.<br />Ledger type for finding.</>} />
          <div className="cc-plate cc-type-grid"><article className="cc-type-specimen cc-type-specimen--wide"><p className="cc-label">display</p><p className="cc-display">Leave a little<br /><em>space for wonder.</em></p></article><article className="cc-type-specimen"><p className="cc-label">h1 / h2 / h3</p><p className="cc-h1">A generous title</p><p className="cc-h2">A section title</p><p className="cc-h3">A useful subheading</p></article><article className="cc-type-specimen"><p className="cc-label">body / lead</p><p className="cc-body">The body style keeps longer notes calm, clear, and close to the paper.</p><p className="cc-lead">Lead copy can open a small door into the next thing.</p></article><article className="cc-type-specimen"><p className="cc-label">caption / label / mono</p><p className="cc-caption">a caption for the quiet detail</p><p className="cc-label">small practical label</p><p className="cc-mono">DEMO / SAMPLE RECORD / 08:42</p></article></div>
        </section>

        <section className="cc-section" id="controls" aria-labelledby="controls-title">
          <SectionHeading eyebrow="04 / controls" id="controls-title" title={<>Recessed wells<br /><em>for making a mark.</em></>} aside={<>Native controls first.<br />Clear labels always.</>} />
          <div className="cc-controls-layout"><article className="cc-plate cc-form-plate"><div className="cc-panel-heading"><p className="cc-label">interactive demonstration</p><h3 className="cc-h3">Add a sample beer die record</h3><p className="cc-body">This form validates and confirms locally. Nothing leaves the page.</p></div><DemoForm showToast={showToast} /></article><aside className="cc-plate cc-control-rail" aria-labelledby="control-states-title"><div className="cc-panel-heading"><p className="cc-label">control states</p><h3 className="cc-h3" id="control-states-title">A clear error is kind.</h3></div><div className="cc-field cc-field--error"><label className="cc-label" htmlFor="error-email">email / error specimen</label><input className="cc-input" id="error-email" type="email" defaultValue="not-an-email" aria-invalid="true" aria-describedby="error-email-message" /><p className="cc-field__error" id="error-email-message" role="alert">Use an email like hello@example.com.</p></div><div className="cc-control-rail__rule" aria-hidden="true" /><div className="cc-field"><label className="cc-label" htmlFor="native-select">native select</label><select className="cc-select" id="native-select"><option>one small choice</option><option>another small choice</option></select></div><div className="cc-choice-row cc-choice-row--stacked"><label className="cc-choice"><input type="checkbox" defaultChecked /> checkbox / selected</label><label className="cc-choice"><input type="radio" name="state-radio" defaultChecked /> radio / selected</label><label className="cc-choice cc-choice--muted"><input type="checkbox" disabled /> disabled native control</label></div></aside></div>
        </section>

        <section className="cc-section" id="tabs" aria-labelledby="tabs-title">
          <SectionHeading compact eyebrow="05 / segmented views" id="tabs-title" title={<>Three small views<br /><em>of the same shelf.</em></>} aside={<>Use the tabs.<br />The room stays familiar.</>} />
          <div className="cc-tabs cc-plate"><div className="cc-segmented" role="tablist" aria-label="Demo shelf views">{tabs.map((tab) => <button key={tab.id} className="cc-segmented__item" id={`tab-${tab.id}`} type="button" role="tab" aria-controls={`panel-${tab.id}`} aria-selected={activeTab === tab.id} onClick={() => setActiveTab(tab.id)}>{tab.label}</button>)}</div><section className="cc-tabs__panel" id={`panel-${activePanel.id}`} role="tabpanel" aria-labelledby={`tab-${activePanel.id}`} tabIndex="0"><p className="cc-label">{activePanel.eyebrow}</p><h3 className="cc-h3">{activePanel.title}</h3><p className="cc-body">{activePanel.body}</p></section></div>
        </section>

        <section className="cc-section" id="feedback" aria-labelledby="feedback-title">
          <SectionHeading compact eyebrow="06 / feedback" id="feedback-title" title={<>A few signals<br /><em>worth listening for.</em></>} />
          <div className="cc-feedback-grid"><div className="cc-notice cc-notice--success" role="status"><span className="cc-notice__mark" aria-hidden="true">✓</span><div><strong>success notice</strong><p>Saved locally. The sample stays in this page.</p></div></div><div className="cc-notice cc-notice--error" role="alert"><span className="cc-notice__mark" aria-hidden="true">!</span><div><strong>error notice</strong><p>There is one small thing to fix before continuing.</p></div></div></div>
          <div className="cc-metrics-grid"><article className="cc-card cc-card--inset"><p className="cc-label">badge set</p><div className="cc-badge-row"><span className="cc-badge cc-badge--accent">accent</span><span className="cc-badge cc-badge--soft">quiet</span><span className="cc-badge cc-badge--outline">outline</span><span className="cc-badge cc-badge--demo">demo</span></div></article><article className="cc-card cc-card--elevated"><p className="cc-label">avatar / sample circle</p><div className="cc-avatar-row"><span className="cc-avatar cc-avatar--clay" aria-label="Mina, demo player">M</span><span className="cc-avatar cc-avatar--moss" aria-label="Jo, demo player">J</span><span className="cc-avatar cc-avatar--walnut" aria-label="Kai, demo player">K</span><span className="cc-mono">3 demo players</span></div></article><article className="cc-card cc-card--elevated cc-progress-card"><div className="cc-progress-card__heading"><p className="cc-label">progress / sample stat</p><output htmlFor="shelf-progress">68%</output></div><progress id="shelf-progress" value="68" max="100" aria-label="Demo shelf completion">68%</progress><p className="cc-caption">demo shelf completion / not live activity</p></article></div>
        </section>

        <section className="cc-section" id="disclosure" aria-labelledby="disclosure-title">
          <SectionHeading compact eyebrow="07 / disclosure" id="disclosure-title" title={<>Details can stay<br /><em>under a fold.</em></>} />
          <div className="cc-accordion-stack"><details className="cc-accordion" open><summary>What does the inset surface mean?</summary><div className="cc-accordion__content"><p className="cc-body">Use it for a related group that is present but not asking to be noticed first. Its shadow falls inward, like a shallow ceramic well.</p></div></details><details className="cc-accordion"><summary>Why are the corners a little uneven?</summary><div className="cc-accordion__content"><p className="cc-body">The asymmetry is a material cue, not a usability tax. Borders, labels, and target sizes stay predictable even when the paper edge does not.</p></div></details><details className="cc-accordion"><summary>What happens without JavaScript?</summary><div className="cc-accordion__content"><p className="cc-body">The room link, navigation, native form controls, notices, and tab content remain available. The accordion remains native HTML.</p></div></details></div>
        </section>

        <section className="cc-section cc-overlay-section" id="overlays" aria-labelledby="overlays-title">
          <SectionHeading compact eyebrow="08 / overlays" id="overlays-title" title={<>A small pause<br /><em>when it helps.</em></>} aside={<>Dialog closes by button<br />or Escape.</>} />
          <div className="cc-overlay-actions cc-plate"><div><p className="cc-label">dialog</p><h3 className="cc-h3">Ask before the next step.</h3><p className="cc-body">The native dialog carries focus, backdrop, and Escape behavior.</p></div><div className="cc-button-row"><button className="cc-button cc-button--secondary" type="button" onClick={openDialog}>open dialog</button><button className="cc-button cc-button--ghost" type="button" onClick={() => showToast('Toast shown — still on this page')}>show a toast</button></div></div>
        </section>

        <dialog ref={dialogRef} className="cc-dialog" id="sample-dialog" aria-labelledby="sample-dialog-title" onClose={() => setDialogOpen(false)} onClick={(event) => { if (event.target === event.currentTarget) closeDialog(); }} onKeyDown={(event) => { if (event.key === 'Escape') closeDialog(); }}><div><button className="cc-dialog__close" type="button" aria-label="Close dialog" onClick={closeDialog}>×</button><Kicker>local confirmation</Kicker><h2 className="cc-h2" id="sample-dialog-title">Leave a light on?</h2><p className="cc-body">This is a native dialog demonstration. No record is created and no network request is made.</p><div className="cc-dialog__actions"><button className="cc-button cc-button--ghost" type="button" onClick={closeDialog}>not now</button><button className="cc-button cc-button--primary" type="button" onClick={() => { closeDialog(); showToast('Dialog confirmed locally — no record was created.'); }}>keep the note</button></div></div></dialog>
        {toast && <div className="cc-toast" role="status" aria-live="polite"><span className="cc-toast__mark" aria-hidden="true">·</span><span>{toast}</span><button className="cc-toast__close" type="button" onClick={() => setToast(null)} aria-label="Dismiss toast">×</button></div>}
      </main>

      <footer className="cc-footer"><p className="cc-mono">cozy commons / common UI / chosen direction</p><div className="cc-footer__links"><Link to="/">return to landing room</Link><Link to="/dice">Dice app ↗</Link></div></footer>
    </div>
  );
}
