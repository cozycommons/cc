import { useEffect, useMemo, useRef, useState } from 'react';
import { useLocation, useNavigate } from 'react-router-dom';
import { Armchair, BedDouble, BrickWall, Circle, Cloud, CloudOff, DoorOpen, Hand, Link2, LoaderCircle, Minus, Monitor, MousePointer2, PanelTop, Pencil, Redo2, RotateCcw, Scan, Square, Trash2, Undo2, UserPlus, Users, X } from 'lucide-react';
import EditorCanvas from './EditorCanvas';
import { formatInches, roundInch } from './geometry';
import { createInitialScene } from './initialScene';
import { blankScene, useFloorPlanDocument, usePlannerAuth, listFloorPlans, createFloorPlan, updateFloorPlan, deleteFloorPlan, listFloorPlanInvitations, addFloorPlanInvitation, revokeFloorPlanInvitation } from './useFloorPlanDocument';
import './floor-planner.css';

export const TOOLS = [['select','Select',MousePointer2],['hand','Hand',Hand],['wall','Wall',BrickWall],['door','Door gap',DoorOpen],['window','Window',PanelTop],['rectangle','Rectangle',Square],['ellipse','Ellipse',Circle],['line','Line',Minus],['draw','Draw',Pencil],['bed','Queen bed',BedDouble],['desk','55″ desk',Monitor],['chair','Chair',Armchair]];
const APARTMENT_SCENE_LABEL = 'Measured apartment';

function planHref(id) { return `/floor-planner/plans/${encodeURIComponent(id)}`; }

export default function FloorPlannerApp() {
  const { supabase, user, loading: authLoading, signIn } = usePlannerAuth();
  const location = useLocation();
  const navigate = useNavigate();
  const planId = location.pathname.match(/^\/floor-planner\/plans\/([^/]+)/)?.[1];
  if (!planId) return <FloorPlanLibrary key={user?.id ?? 'anonymous'} supabase={supabase} user={user} authLoading={authLoading} signIn={signIn} navigate={navigate} />;
  return <FloorPlanEditor key={`${planId}:${user?.id ?? 'anonymous'}`} planId={planId} supabase={supabase} user={user} signIn={signIn} navigate={navigate} />;
}

function FloorPlanLibrary({ supabase, user, authLoading, signIn, navigate }) {
  const [plans, setPlans] = useState({ mine: [], shared: [], public: [] });
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [sharePlan, setSharePlan] = useState(null);
  const [notice, setNotice] = useState('');

  const reload = async () => {
    setLoading(true);
    setError('');
    try { setPlans(await listFloorPlans(supabase, user?.id)); }
    catch (failure) { setError(failure.message); }
    finally { setLoading(false); }
  };
  useEffect(() => { let active = true; setLoading(true); setError(''); listFloorPlans(supabase, user?.id).then((value) => { if (active) setPlans(value); }).catch((failure) => { if (active) setError(failure.message); }).finally(() => { if (active) setLoading(false); }); return () => { active = false; }; }, [supabase, user?.id]);

  const create = async (template) => {
    if (!user) { await signIn(); return; }
    setBusy(true); setError('');
    try {
      const plan = await createFloorPlan(supabase, user.id, template, template === 'apartment' ? 'Apartment plan' : 'Untitled plan');
      navigate(planHref(plan.id));
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  };
  const mutateOwnerPlan = async (plan, action) => {
    if (!user) return;
    setBusy(true); setError('');
    try {
      if (action === 'rename') {
        const title = window.prompt('Plan name', plan.title);
        if (title === null) return;
        if (!title.trim()) { setError('Enter a plan name.'); return; }
        await updateFloorPlan(supabase, user.id, plan.id, plan.revision, { title: title.trim() });
      } else if (action === 'visibility') {
        const visibility = plan.visibility === 'public' ? 'private' : 'public';
        await updateFloorPlan(supabase, user.id, plan.id, plan.revision, { visibility });
        setNotice(visibility === 'public' ? 'Plan added to the public gallery.' : 'Plan removed from the public gallery.');
      } else if (action === 'delete') {
        if (!window.confirm(`Delete “${plan.title}”? This cannot be undone.`)) return;
        await deleteFloorPlan(supabase, user.id, plan.id);
      }
      await reload();
    } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  };

  return <main className="fp-library">
    <header className="fp-library-head"><a href="/" className="fp-brand">COZY COMMONS <span>/</span> PROJECTS</a><div>{user ? <span className="fp-account">{user.email}</span> : !authLoading && <button className="fp-button" onClick={signIn}>Sign in</button>}</div></header>
    <div className="fp-content">
      <div className="fp-title-row"><div><p className="fp-eyebrow">COZY COMMONS · FLOOR PLANNER</p><h1>Floor plans</h1></div><div className="fp-create-actions"><button disabled={busy} onClick={() => create('blank')}>New blank plan</button><button className="fp-button-primary" disabled={busy} onClick={() => create('apartment')}>Start from apartment</button></div></div>
      {error && <p className="fp-alert" role="alert">{error}</p>}{notice && <p className="fp-notice" role="status">{notice}</p>}
      {loading ? <p className="fp-loading"><LoaderCircle size={16} className="fp-spin" /> Loading plans…</p> : <>
        <PlanSection title="My plans" subtitle="Plans you own" plans={plans.mine} empty="Plans you create will live here." owner onOpen={(plan) => navigate(planHref(plan.id))} onAction={mutateOwnerPlan} onShare={setSharePlan} busy={busy} />
        <PlanSection title="Shared with me" subtitle="Invited plans you can edit" plans={plans.shared} empty="Plans shared with your verified email will appear here." onOpen={(plan) => navigate(planHref(plan.id))} showAccess />
        <PlanSection title="Public gallery" subtitle="Anyone can view; only invited people can edit" plans={plans.public} empty="Public plans will appear here." onOpen={(plan) => navigate(planHref(plan.id))} />
      </>}
    </div>
    {sharePlan && <ShareDialog plan={sharePlan} supabase={supabase} user={user} onClose={() => setSharePlan(null)} onChanged={reload} />}
  </main>;
}

function PlanSection({ title, subtitle, plans, empty, owner = false, showAccess = false, onOpen, onAction, onShare, busy }) {
  return <section className="fp-section"><div className="fp-section-head"><h2>{title}</h2><p>{subtitle}</p></div>{plans.length ? <div className="fp-cards">{plans.map((plan) => <article className="fp-card" key={`${title}:${plan.id}`}>
    <button className="fp-card-open" onClick={() => onOpen(plan)}><span className="fp-plan-thumbnail"><FloorPlanThumbnail plan={plan} /></span><span className="fp-plan-name">{plan.title}</span><span className="fp-plan-meta">{plan.template === 'apartment' ? APARTMENT_SCENE_LABEL : 'Blank canvas'} · {plan.visibility === 'public' ? 'Public' : 'Private'}</span></button>
    <div className="fp-card-actions">{owner && <><button disabled={busy} onClick={() => onAction(plan, 'rename')}>Rename</button><button disabled={busy} onClick={() => onShare(plan)}>Share</button><button disabled={busy} onClick={() => onAction(plan, 'visibility')}>{plan.visibility === 'public' ? 'Make private' : 'Make public'}</button><button className="fp-danger-link" disabled={busy} onClick={() => onAction(plan, 'delete')}>Delete</button></>}{showAccess && <span>Can edit</span>}</div>
  </article>)}</div> : <p className="fp-empty">{empty}</p>}</section>;
}

function FloorPlanThumbnail({ plan }) {
  return plan.template === 'apartment'
    ? <svg viewBox="0 0 120 76" aria-hidden="true"><path d="M18 12h84v52H18zM53 12v22h24V12M18 43h35v21M77 34v30" fill="none" stroke="currentColor" strokeWidth="2" /></svg>
    : <svg viewBox="0 0 120 76" aria-hidden="true"><rect x="24" y="10" width="72" height="56" rx="3" fill="none" stroke="currentColor" strokeWidth="2" strokeDasharray="4 4" /><path d="M60 25v26M47 38h26" fill="none" stroke="currentColor" strokeWidth="2" /></svg>;
}

function ShareDialog({ plan, supabase, user, onClose, onChanged }) {
  const dialogRef = useRef(null);
  const [invitations, setInvitations] = useState([]);
  const [email, setEmail] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState(false);
  const load = async () => {
    try { setInvitations(await listFloorPlanInvitations(supabase, user.id, plan.id)); }
    catch (failure) { setError(failure.message); }
  };
  useEffect(() => { void load(); }, [plan.id, user?.id]);
  useEffect(() => { const dialog = dialogRef.current; if (dialog && !dialog.open) dialog.showModal(); }, []);
  const copyLink = async () => {
    await navigator.clipboard.writeText(`${window.location.origin}${planHref(plan.id)}`);
    setCopied(true);
  };
  const add = async (event) => {
    event.preventDefault(); setBusy(true); setError('');
    try { await addFloorPlanInvitation(supabase, user.id, plan.id, email); setEmail(''); await load(); await onChanged(); }
    catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  };
  const revoke = async (id) => {
    setBusy(true); setError('');
    try { await revokeFloorPlanInvitation(supabase, user.id, plan.id, id); await load(); await onChanged(); }
    catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  };
  return <dialog className="fp-share-dialog" ref={dialogRef} aria-labelledby="fp-share-title" onCancel={(event) => { event.preventDefault(); onClose(); }}><section className="fp-share-modal">
    <button className="fp-modal-close" aria-label="Close sharing" onClick={onClose}><X size={18} /></button><p className="fp-eyebrow">PLAN SHARING</p><h2 id="fp-share-title">Share {plan.title}</h2><p className="fp-share-help">Invited people can edit after they sign in with this verified email. Cozy Commons will not email them automatically.</p>
    <button className="fp-copy-link" onClick={copyLink}><Link2 size={16} /> {copied ? 'Link copied' : 'Copy plan link'}</button>
    <form className="fp-invite-form" onSubmit={add}><label htmlFor="fp-invite-email">Invite by email</label><div><input id="fp-invite-email" type="email" required maxLength={254} value={email} onChange={(event) => setEmail(event.target.value)} placeholder="name@example.com" /><button disabled={busy}><UserPlus size={15} /> Invite</button></div></form>
    {error && <p role="alert" className="fp-alert">{error}</p>}
    <div className="fp-invitation-list"><h3>People with edit access</h3>{invitations.length ? invitations.map((item) => <div className="fp-invitation" key={item.id}><span><strong>{item.email}</strong><small>{item.status === 'connected' ? 'Verified account connected' : 'Waiting for verified sign-in'}</small></span><button disabled={busy} onClick={() => revoke(item.id)}>Remove</button></div>) : <p>No invitations yet.</p>}</div>
  </section></dialog>;
}

function FloorPlanEditor({ planId, supabase, user, signIn, navigate }) {
  const { scene, setScene, document, status, message, canEdit, isOwner, draftAvailable, restoreDraft, discardDraft } = useFloorPlanDocument(planId, supabase, user);
  const [tool, setTool] = useState('select');
  const [selectedId, setSelectedId] = useState(null);
  const [fitSignal, setFitSignal] = useState(0);
  const [history, setHistory] = useState({ past: [], future: [] });
  const [shareOpen, setShareOpen] = useState(false);
  const transactionStart = useRef(null);
  const navigateHome = () => navigate('/floor-planner');
  const selected = useMemo(() => scene.elements.find((element) => element.id === selectedId), [scene.elements, selectedId]);
  const applyChange = (update) => { if (!canEdit) return; setHistory((current) => ({ past: [...current.past, scene], future: [] })); setScene(update); };
  const beginTransaction = () => { if (!transactionStart.current) transactionStart.current = scene; };
  const endTransaction = () => { if (!transactionStart.current) return; const before = transactionStart.current; transactionStart.current = null; setHistory((current) => ({ past: [...current.past, before], future: [] })); };
  const undo = () => setHistory((current) => { if (!canEdit || !current.past.length) return current; const previous = current.past.at(-1); setScene(previous); setSelectedId(null); return { past: current.past.slice(0, -1), future: [scene, ...current.future] }; });
  const redo = () => setHistory((current) => { if (!canEdit || !current.future.length) return current; const next = current.future[0]; setScene(next); setSelectedId(null); return { past: [...current.past, scene], future: current.future.slice(1) }; });
  const updateSelected = (patch) => applyChange((current) => ({ ...current, elements: current.elements.map((element) => element.id === selectedId ? { ...element, ...patch } : element) }));
  const removeSelected = () => { if (!canEdit) return; applyChange((current) => ({ ...current, elements: current.elements.filter((element) => element.id !== selectedId) })); setSelectedId(null); };
  const reset = () => {
    if (!canEdit || !window.confirm(`Reset this plan to ${document?.template === 'apartment' ? 'the measured apartment' : 'a blank canvas'}? Added drawings will be removed.`)) return;
    applyChange(document?.template === 'apartment' ? createInitialScene() : blankScene()); setSelectedId(null); setFitSignal((value) => value + 1);
  };
  useEffect(() => { const onKeyDown = (event) => { if (!canEdit || event.target instanceof HTMLElement && event.target.matches('input, textarea, [contenteditable="true"]') || !(event.metaKey || event.ctrlKey) || event.key.toLowerCase() !== 'z') return; event.preventDefault(); if (event.shiftKey) redo(); else undo(); }; window.addEventListener('keydown', onKeyDown); return () => window.removeEventListener('keydown', onKeyDown); });

  if (status === 'loading') return <AuthGate message="Loading plan…" />;
  if (status === 'load-error' || status === 'access-error') return <AuthGate message={message} onHome={navigateHome} onSignIn={!user ? signIn : null} recoveryScene={draftAvailable ? scene : null} />;

  return <main className="floor-editor">
    <header className="editor-header"><div className="editor-heading"><button className="fp-back" onClick={navigateHome}>← Plans</button><div><p className="editor-kicker">{document?.visibility === 'public' ? 'Public plan' : 'Private plan'} · inches</p><h1>{document?.title || 'FLOOR PLAN EDITOR'}</h1></div></div><div className="editor-header-actions"><span className={`save-status status-${status}`}><Cloud size={14} />{message}</span>{status === 'conflict' && <button className="text-button" onClick={() => window.location.reload()}>Reload latest</button>}{draftAvailable && status === 'saved' && <button className="text-button" onClick={restoreDraft}>Recover local draft</button>}{!user && <button type="button" className="text-button" onClick={signIn}>Sign in</button>}{isOwner && <button type="button" className="icon-text-button" onClick={() => setShareOpen(true)}><Users size={15} /> Share</button>}<button type="button" className="history-button" aria-label="Undo" title="Undo (⌘Z)" disabled={!canEdit || !history.past.length} onClick={undo}><Undo2 size={16} /></button><button type="button" className="history-button" aria-label="Redo" title="Redo (⌘⇧Z)" disabled={!canEdit || !history.future.length} onClick={redo}><Redo2 size={16} /></button><button type="button" className="icon-text-button" onClick={() => setFitSignal((value) => value + 1)}><Scan size={16} /> Fit</button><button type="button" className="icon-text-button" disabled={!canEdit} onClick={reset}><RotateCcw size={16} /> Reset</button></div></header>
    {['error','conflict','revoked'].includes(status) && <div className="fp-save-warning" role="status"><CloudOff size={15} /><span>{message}</span>{draftAvailable && canEdit && <button onClick={restoreDraft}>Recover local draft</button>}{draftAvailable && <button onClick={discardDraft}>Discard draft</button>}</div>}
    <div className="editor-body"><nav className="tool-rail" aria-label="Floor plan tools">{TOOLS.map(([id,label,Icon]) => { const disabled = !canEdit && !['select', 'hand'].includes(id); return <button key={id} type="button" className={tool === id ? 'active' : ''} aria-label={label} title={disabled ? `${label} (write access required)` : label} disabled={disabled} onClick={() => setTool(id)}><Icon size={19} /><span>{label}</span></button>; })}</nav><section className="canvas-shell"><EditorCanvas scene={scene} setScene={setScene} tool={tool} setTool={setTool} selectedId={selectedId} setSelectedId={setSelectedId} fitSignal={fitSignal} onTransactionStart={beginTransaction} onTransactionEnd={endTransaction} onDeleteSelected={removeSelected} readOnly={!canEdit} /><div className="canvas-hint">{canEdit ? 'Drag to pan · scroll or pinch to zoom · 2″ snap · ⌘/Ctrl+Z undo' : 'Read-only · drag to pan · scroll or pinch to zoom'}</div></section><aside className="property-panel" aria-label="Element properties"><p className="editor-kicker">Properties</p>{!selected && <div className="empty-inspector"><MousePointer2 size={22} /><p>Select an item to inspect its real-world measurements.</p></div>}{selected && <Inspector element={selected} onChange={updateSelected} onRemove={removeSelected} readOnly={!canEdit} />}</aside></div>
    {shareOpen && isOwner && <ShareDialog plan={document} supabase={supabase} user={user} onClose={() => setShareOpen(false)} onChanged={() => {}} />}
  </main>;
}

function AuthGate({ message, onSignIn, onHome, recoveryScene }) {
  const download = () => {
    const link = document.createElement('a');
    link.href = URL.createObjectURL(new Blob([JSON.stringify(recoveryScene, null, 2)], { type: 'application/json' }));
    link.download = 'floor-plan-recovery.json'; link.click(); URL.revokeObjectURL(link.href);
  };
  return <main className="floor-editor floor-editor-gate"><div className="gate-card"><p className="editor-kicker">Cozy Commons · Floor Planner</p><h1>FLOOR PLANNER</h1><p className="gate-message">{message}</p>{onSignIn && <button type="button" className="icon-text-button" onClick={onSignIn}>Sign in to view plan</button>}{onHome && <button type="button" className="icon-text-button" onClick={onHome}>Back to plans</button>}{recoveryScene && <button type="button" className="icon-text-button" onClick={download}>Download local draft</button>}</div></main>;
}

function Inspector({ element, onChange, onRemove, readOnly = false }) {
  const isLine = element.type === 'line';
  const hasRect = ['furniture','rectangle','ellipse'].includes(element.type);
  const label = element.label ?? element.kind ?? element.furnitureType ?? element.type;
  const field = (labelText, key, value, suffix='in') => <label><span>{labelText}</span><div><input type="number" step="0.25" value={roundInch(value ?? 0)} readOnly={readOnly} onChange={(event) => onChange({ [key]: Number(event.target.value) })} /><em>{suffix}</em></div></label>;
  return <div className="inspector-content"><h2>{label}</h2><p className="measurement-summary">{isLine ? 'Measured line' : element.type === 'wall' ? formatInches(element.length) : element.type === 'opening' ? formatInches(element.width) : hasRect ? `${formatInches(element.width)} × ${formatInches(element.height)}` : 'Drawing'}</p>{readOnly && <p className="measurement-summary">Read-only access</p>}{!isLine && element.type !== 'freehand' && <div className="field-grid">{field('X','x',element.x)}{field('Y','y',element.y)}{field('Rotation','rotation',element.rotation ?? 0,'°')}{element.type === 'wall' && field('Length','length',element.length)}{element.type === 'opening' && field('Width','width',element.width)}{hasRect && field('Width','width',element.width)}{hasRect && field('Height','height',element.height)}{['wall','opening'].includes(element.type) && field('Thickness','thickness',element.thickness)}</div>}{!readOnly && <button type="button" className="remove-button" onClick={onRemove}><Trash2 size={15} /> Remove</button>}</div>;
}
