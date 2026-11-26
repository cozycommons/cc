import DataShowcase from './DataShowcase.jsx';
import SiteHeader from '../components/SiteHeader.jsx';
import React from 'react';
import { Link } from 'react-router-dom';
import '../../../design/cozy-wabi/components.css';
import {
  Accordion, AccordionHeader, AccordionItem, AccordionPanel, AccordionTrigger,
  Button, Choice, createToaster, Dialog, DialogBackdrop, DialogClose, DialogContent,
  DialogDescription, DialogTitle, DialogTrigger, Input, PersonAvatar, Progress, ProgressIndicator,
  ProgressTrack, Radio, RadioGroup, RadioIndicator, SelectField, Slider, SliderControl,
  SliderIndicator, SliderThumb, SliderTrack, SliderValue, Switch, SwitchThumb, Tabs,
  TabsList, TabsPanel, TabsTab, Textarea, Toasts,
} from './system/Controls.jsx';

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
  const [kind, setKind] = React.useState(null);
  const [remember, setRemember] = React.useState(false);

  const submit = (event) => {
    event.preventDefault();
    const nextErrors = {};
    const name = nameRef.current;
    const email = emailRef.current;

    if (!name.value.trim()) nextErrors.name = 'Add a name before continuing.';
    if (!email.value.trim() || !email.validity.valid) nextErrors.email = 'Use an email like hello@example.com.';
    if (!kind) nextErrors.kind = 'Choose one small record type.';
    if (!remember) nextErrors.remember = 'Check this before continuing.';

    setErrors(nextErrors);
    if (Object.keys(nextErrors).length > 0) {
      setStatus('A few small details need your attention.');
      const controls = { name, email, kind: kindRef.current, remember: rememberRef.current };
      controls[Object.keys(nextErrors)[0]]?.focus();
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
          <Input id="record-name" name="name" type="text" autoComplete="name" required aria-invalid={Boolean(errors.name)} aria-describedby="record-name-help" ref={nameRef} onValueChange={() => clearError('name')} />
          <p className="cc-help" id="record-name-help">A local sample player name.</p>
          {errors.name && <p className="cc-field__error" role="alert">{errors.name}</p>}
        </div>
        <div className={`cc-field${errors.email ? ' cc-field--error' : ''}`}>
          <label className="cc-label" htmlFor="record-email">email <span className="cc-field__required">required</span></label>
          <Input id="record-email" name="email" type="email" autoComplete="email" required aria-invalid={Boolean(errors.email)} ref={emailRef} onValueChange={() => clearError('email')} />
          {errors.email && <p className="cc-field__error" role="alert">{errors.email}</p>}
        </div>
        <div className="cc-field">
          <label className="cc-label" htmlFor="record-search">search records</label>
          <Input id="record-search" name="search" type="search" placeholder="e.g. patio rematch" />
        </div>
        <div className={`cc-field${errors.kind ? ' cc-field--error' : ''}`}>
          <SelectField label="record type required" placeholder="Choose a type" value={kind} onValueChange={(value) => { setKind(value); clearError('kind'); }}
            triggerProps={{ ref: kindRef, 'aria-invalid': Boolean(errors.kind) }}
            options={[{ value: 'round', label: 'round' }, { value: 'rematch', label: 'rematch' }, { value: 'tournament', label: 'tiny tournament' }]} />
          {errors.kind && <p className="cc-field__error" role="alert">{errors.kind}</p>}
        </div>
      </div>

      <div className="cc-field">
        <label className="cc-label" htmlFor="record-note">field note</label>
        <Textarea id="record-note" name="note" rows="4" placeholder="What is worth remembering?" />
      </div>

      <fieldset className="cc-fieldset">
        <legend className="cc-label">record mood</legend>
        <RadioGroup className="cc-choice-row" aria-label="Record mood" defaultValue="steady" name="mood">
          {['steady', 'lively', 'legendary'].map((mood) => <label className="cc-choice" key={mood}><Radio className="cc-sdk-radio" value={mood}><RadioIndicator /></Radio> {mood}</label>)}
        </RadioGroup>
      </fieldset>

      <div className="cc-form__split">
        <label className="cc-switch">
          <Switch className="cc-switch__track cc-sdk-switch" name="reminder" defaultChecked><SwitchThumb className="cc-switch__thumb" /></Switch>
          <span className="cc-label">keep a local reminder</span>
        </label>
        <Slider className="cc-range-field" defaultValue={68} name="warmth">
          <div className="cc-label">paper warmth <SliderValue /></div>
          <SliderControl className="cc-sdk-slider-control"><SliderTrack className="cc-sdk-slider-track">
            <SliderIndicator className="cc-sdk-slider-indicator" /><SliderThumb className="cc-sdk-slider-thumb" aria-label="Paper warmth" />
          </SliderTrack></SliderControl>
        </Slider>
      </div>

      <Choice className="cc-choice--consent" ref={rememberRef} checked={remember} aria-invalid={Boolean(errors.remember)}
        onCheckedChange={(checked) => { setRemember(checked); clearError('remember'); }}>
        I understand this is demo data.
      </Choice>
      {errors.remember && <p className="cc-field__error" role="alert">{errors.remember}</p>}
      <div className="cc-form__actions">
        <Button variant="primary" type="submit">Confirm locally</Button>
        <p className={`cc-form__status${status.startsWith('Confirmed') ? ' is-success' : status ? ' is-error' : ''}`} role="status" aria-live="polite">{status}</p>
      </div>
    </form>
  );
}

export default function DesignIndex() {
  const [menuOpen, setMenuOpen] = React.useState(false);
  const [showToast] = React.useState(() => createToaster());
  useBodyClass('cc-components-body');

  React.useEffect(() => () => showToast.dismiss(), [showToast]);

  const tabs = [
    { id: 'room', label: 'room notes', eyebrow: 'demo room', title: 'The lamp is a local pool of amber.', body: 'Nothing here claims to be live. It is a composed little room for seeing how a surface might feel.' },
    { id: 'records', label: 'records', eyebrow: 'sample stats', title: 'Dice keeps the friendly arguments.', body: <>Demo record: patio rematch / 3 rounds / 2 players. The actual app lives at <Link className="cc-inline-link" to="/dice">/dice</Link>.</> },
    { id: 'rituals', label: 'rituals', eyebrow: 'quiet ritual', title: 'Open, notice, leave a light on.', body: 'A tab is useful when the content changes but the place stays familiar.' },
  ];

  return (
    <div className="cc-page">
      <SiteHeader>
        <p className="cc-navbar__note">living system / no live data</p>
        <Button variant="ghost" className="cc-menu-toggle" type="button" aria-expanded={menuOpen} aria-controls="cc-site-navigation" onClick={() => setMenuOpen((open) => !open)}>
          <span className="cc-menu-toggle__label">{menuOpen ? 'close menu' : 'open menu'}</span>
        </Button>
        <nav className={`cc-navbar__links${menuOpen ? '' : ' is-collapsed'}`} id="cc-site-navigation" aria-label="Component library navigation">
          <Link to="/">homepage</Link>
          <a href="#data-patterns">data & interaction</a>
          <a href="#buttons">inventory</a>
          <Link to="/dice">Dice ↗</Link>
        </nav>
      </SiteHeader>

      <main>
        <section className="cc-hero" aria-labelledby="library-title">
          <div className="cc-hero__copy">
            <Kicker>common room / reusable pieces</Kicker>
            <h1 className="cc-display" id="library-title">Cozy Commons<br /><em>Design system.</em></h1>
            <p className="cc-lead">Components, materials, and interaction patterns for the next project.</p>
            <div className="cc-hero__actions"><a className="cc-button cc-button--primary" href="#buttons">Browse inventory <span aria-hidden="true">↘</span></a><Link className="cc-button cc-button--ghost" to="/">Back to the room</Link></div>
          </div>
        </section>

        <div className="cc-inventory-bar" aria-label="Specimen inventory">
          <span>01 actions</span><span>02 surfaces</span><span>03 type</span><span>04 controls</span><span>05 feedback</span><span>06 overlays</span>
          <span className="cc-inventory-bar__palette">warm washi · iron glaze · burnt sienna · local amber</span>
        </div>

        <DataShowcase />

        <section className="cc-section" id="buttons" aria-labelledby="buttons-title">
          <SectionHeading compact eyebrow="01 / actions" id="buttons-title" title={<>Raised keys<br /><em>with a soft landing.</em></>} aside={<>Hover, focus, press,<br />disabled, and loading.</>} />
          <div className="cc-plate cc-action-plate"><div className="cc-button-row" aria-label="Button variants"><Button variant="primary" type="button" onClick={() => showToast('Primary action acknowledged.')}>Primary</Button><Button variant="secondary" type="button" onClick={() => showToast('Secondary action acknowledged.')}>Secondary</Button><Button variant="ghost" type="button">Ghost</Button><Button variant="destructive" type="button">Destructive</Button><Button variant="secondary" className="cc-button--icon" type="button" aria-label="Add a sample record" title="Add a sample record" onClick={() => showToast('Add record is local.')}>+</Button><Button variant="primary" className="cc-button--small" type="button">Small</Button><Button variant="secondary" className="cc-button--active" type="button" aria-pressed="true">Active</Button><Button variant="primary" type="button" disabled>Disabled</Button><Button variant="primary" className="cc-button--loading" type="button" aria-busy="true" disabled><span className="cc-spinner" aria-hidden="true" />Loading</Button></div><p className="cc-caption">Every action keeps a 44px minimum target. The pressed sample is a static state; the loading sample is intentionally local.</p></div>
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
          <SectionHeading eyebrow="04 / controls" id="controls-title" title={<>Recessed wells<br /><em>for making a mark.</em></>} aside={<>Labeled controls.<br />Clear labels always.</>} />
          <div className="cc-controls-layout"><article className="cc-plate cc-form-plate"><div className="cc-panel-heading"><p className="cc-label">interactive demonstration</p><h3 className="cc-h3">Add a sample beer die record</h3><p className="cc-body">This form validates and confirms locally. Nothing leaves the page.</p></div><DemoForm showToast={showToast} /></article><aside className="cc-plate cc-control-rail" aria-labelledby="control-states-title"><div className="cc-panel-heading"><p className="cc-label">control states</p><h3 className="cc-h3" id="control-states-title">A clear error is kind.</h3></div><div className="cc-field cc-field--error"><label className="cc-label" htmlFor="error-email">email / error specimen</label><Input id="error-email" type="email" defaultValue="not-an-email" aria-invalid="true" aria-describedby="error-email-message" /><p className="cc-field__error" id="error-email-message" role="alert">Use an email like hello@example.com.</p></div><div className="cc-control-rail__rule" aria-hidden="true" /><div className="cc-field"><SelectField label="Select example" defaultValue="one" options={[{ value: "one", label: "one small choice" }, { value: "another", label: "another small choice" }]} /></div><div className="cc-choice-row cc-choice-row--stacked"><Choice defaultChecked>checkbox / selected</Choice><RadioGroup aria-label="Radio example" defaultValue="selected"><label className="cc-choice"><Radio className="cc-sdk-radio" value="selected"><RadioIndicator /></Radio> radio / selected</label></RadioGroup><Choice className="cc-choice--muted" disabled>disabled control</Choice></div></aside></div>
        </section>

        <section className="cc-section" id="tabs" aria-labelledby="tabs-title">
          <SectionHeading compact eyebrow="05 / segmented views" id="tabs-title" title={<>Three small views<br /><em>of the same shelf.</em></>} aside={<>Use the tabs.<br />The room stays familiar.</>} />
          <Tabs className="cc-tabs cc-plate" defaultValue="room">
            <TabsList className="cc-segmented" aria-label="Demo shelf views">{tabs.map(tab => <TabsTab key={tab.id} className="cc-segmented__item" value={tab.id}>{tab.label}</TabsTab>)}</TabsList>
            {tabs.map(tab => <TabsPanel key={tab.id} className="cc-tabs__panel" value={tab.id}><p className="cc-label">{tab.eyebrow}</p><h3 className="cc-h3">{tab.title}</h3><p className="cc-body">{tab.body}</p></TabsPanel>)}
          </Tabs>
        </section>

        <section className="cc-section" id="feedback" aria-labelledby="feedback-title">
          <SectionHeading compact eyebrow="06 / feedback" id="feedback-title" title={<>A few signals<br /><em>worth listening for.</em></>} />
          <div className="cc-feedback-grid"><div className="cc-notice cc-notice--success" role="status"><span className="cc-notice__mark" aria-hidden="true">✓</span><div><strong>success notice</strong><p>Saved locally. The sample stays in this page.</p></div></div><div className="cc-notice cc-notice--error" role="alert"><span className="cc-notice__mark" aria-hidden="true">!</span><div><strong>error notice</strong><p>There is one small thing to fix before continuing.</p></div></div></div>
          <div className="cc-metrics-grid"><article className="cc-card cc-card--inset"><p className="cc-label">badge set</p><div className="cc-badge-row"><span className="cc-badge cc-badge--accent">accent</span><span className="cc-badge cc-badge--soft">quiet</span><span className="cc-badge cc-badge--outline">outline</span><span className="cc-badge cc-badge--demo">demo</span></div></article><article className="cc-card cc-card--elevated"><p className="cc-label">avatar / sample circle</p><div className="cc-avatar-row"><PersonAvatar tone="clay" name="Mina, demo player" /><PersonAvatar tone="moss" name="Jo, demo player" /><PersonAvatar tone="walnut" name="Kai, demo player" /><span className="cc-mono">3 demo players</span></div></article><article className="cc-card cc-card--elevated cc-progress-card"><div className="cc-progress-card__heading"><p className="cc-label">progress / sample stat</p><output htmlFor="shelf-progress">68%</output></div><Progress value={68} max={100} aria-label="Demo shelf completion"><ProgressTrack className="cc-sdk-progress"><ProgressIndicator /></ProgressTrack></Progress><p className="cc-caption">demo shelf completion / not live activity</p></article></div>
        </section>

        <section className="cc-section" id="disclosure" aria-labelledby="disclosure-title">
          <SectionHeading compact eyebrow="07 / disclosure" id="disclosure-title" title={<>Details can stay<br /><em>under a fold.</em></>} />
          <Accordion className="cc-accordion-stack" defaultValue={['inset']}>
            {[
              ['inset', 'What does the inset surface mean?', 'Use it for related controls or details. The inset shadow creates a recessed surface.'],
              ['corners', 'Why are the corners a little uneven?', 'The asymmetric corners echo paper edges. Labels and target sizes stay consistent.'],
            ].map(([value, title, body]) => <AccordionItem className="cc-accordion" value={value} key={value}>
              <AccordionHeader className="cc-accordion__heading"><AccordionTrigger className="cc-accordion__trigger">{title}</AccordionTrigger></AccordionHeader>
              <AccordionPanel className="cc-accordion__content"><p className="cc-body">{body}</p></AccordionPanel>
            </AccordionItem>)}
          </Accordion>
        </section>

        <section className="cc-section cc-overlay-section" id="overlays" aria-labelledby="overlays-title">
          <SectionHeading compact eyebrow="08 / overlays" id="overlays-title" title={<>A small pause<br /><em>when it helps.</em></>} aside={<>Dialog closes by button<br />or Escape.</>} />
          <Dialog>
            <div className="cc-overlay-actions cc-plate"><div><p className="cc-label">dialog</p><h3 className="cc-h3">Confirm an action</h3><p className="cc-body">Focus returns to the trigger when the dialog closes.</p></div>
              <div className="cc-button-row"><DialogTrigger className="cc-button cc-button--secondary">Open dialog</DialogTrigger><Button variant="ghost" onClick={() => showToast('Toast shown — still on this page')}>Show a toast</Button></div>
            </div>
            <DialogBackdrop className="cc-sdk-backdrop" />
            <DialogContent className="cc-sdk-dialog">
              <DialogTitle className="cc-h2">Keep the note?</DialogTitle>
              <DialogDescription className="cc-body">This demonstration saves no record.</DialogDescription>
              <div className="cc-dialog__actions"><DialogClose className="cc-button cc-button--ghost">Not now</DialogClose><DialogClose className="cc-button cc-button--primary" onClick={() => showToast('Dialog confirmed locally — no record was created.')}>Keep the note</DialogClose></div>
            </DialogContent>
          </Dialog>
        </section>
        <Toasts toaster={showToast} />
      </main>

      <footer className="cc-footer"><p className="cc-mono">cozy commons / common UI / chosen direction</p><div className="cc-footer__links"><Link to="/">return to homepage</Link><Link to="/dice">Dice app ↗</Link></div></footer>
    </div>
  );
}
