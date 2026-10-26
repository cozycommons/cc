import React, { useEffect, useRef, useState } from 'react';
import { getClient } from '../supabase.js';
import { adminRequest } from './api.js';
import Chart from './Chart.jsx';
import SiteHeader from '../components/SiteHeader.jsx';
import { ChartColumn } from 'lucide-react';
import { DataRow, SegmentedControl, Skeleton } from '../design/system/DataPatterns.jsx';
import '../../../design/cozy-wabi/components.css';
import './admin.css';

const blank = () => ({ title: '', sql: 'SELECT project, count(*) AS events\nFROM analytics.events\nWHERE created_at >= $1::timestamptz AND created_at < $2::timestamptz\nAND ($3::text IS NULL OR project = $3::text)\nGROUP BY project', visualization: { type: 'table', x: 'project', y: ['events'], series: '' }, position: 0, revision: 1 });
function initialDates() {
  const end = new Date(); const start = new Date(end); start.setUTCDate(start.getUTCDate() - 29);
  return [start.toISOString().slice(0, 10), end.toISOString().slice(0, 10)];
}
function QueryCard({ query, filters, onEdit, refresh }) {
  const [state, setState] = useState({ loading: true });
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    const identity = JSON.stringify([query.sql, query.revision, filters]);
    setState((previous) => ({ loading: true, identity, result: previous.identity === identity ? previous.result : null }));
    adminRequest(`/queries/${query.id}/run`, { method: 'POST', body: filters, signal: controller.signal })
      .then((result) => { if (current) setState({ result, identity }); })
      .catch((error) => { if (current && error.name !== 'AbortError') setState((previous) => ({ ...previous, loading: false, error: error.message })); });
    return () => { current = false; controller.abort(); };
  }, [query, filters, refresh]);
  return <article className="cc-data-panel admin-card" aria-busy={Boolean(state.loading)}>
    <header><h2>{query.title}</h2><div className="admin-card-actions">{state.loading && state.result && <span className="cc-caption" role="status">Refreshing…</span>}<button className="cc-button cc-button--ghost" onClick={() => onEdit(query)}>Edit</button></div></header>
    {state.error && <p className="cc-notice cc-notice--error" role="alert">{state.error}</p>}
    {state.result ? <><Chart result={state.result} config={query.visualization} />{state.result.truncated && <p className="cc-caption">Results truncated</p>}</> : state.loading ? <Skeleton label={`Loading ${query.title}`} /> : null}
  </article>;
}
export default function Admin() {
  const [access, setAccess] = useState('loading');
  const [error, setError] = useState('');
  const [queries, setQueries] = useState([]);
  const [catalog, setCatalog] = useState(null);
  const [dates, setDates] = useState(initialDates);
  const [project, setProject] = useState('');
  const [refresh, setRefresh] = useState(0);
  const [draft, setDraft] = useState(null);
  const [result, setResult] = useState(null);
  const [busy, setBusy] = useState(false);
  const generation = useRef(0);
  const [filters, setFilters] = useState(null);
  useEffect(() => {
    generation.current++; setResult(null);
    const start = new Date(`${dates[0]}T00:00:00Z`); const end = new Date(`${dates[1]}T00:00:00Z`); end.setUTCDate(end.getUTCDate() + 1);
    if (!Number.isFinite(+start) || !Number.isFinite(+end) || end <= start || end - start > 366 * 86400000) { setFilters(null); return; }
    setFilters({ start_at: start.toISOString(), end_at: end.toISOString(), project: project || null });
  }, [dates, project]);
  useEffect(() => {
    let current = true;
    const load = async () => {
      try {
        await adminRequest('/session');
        const saved = await adminRequest('/queries');
        if (current) { setQueries(saved); setAccess('allowed'); setError(''); }
        const schema = await adminRequest('/catalog');
        if (current) setCatalog(schema);
      } catch (err) { if (current) { if (err.status === 401) { setAccess('signed-out'); setError(''); } else if (err.status === 403) { setAccess('denied'); setError(''); } else setError(err.message); } }
    };
    void load();
    let subscription;
    try { subscription = getClient().auth.onAuthStateChange(() => { setTimeout(() => { if (current) void load(); }, 0); }).data.subscription; } catch { setAccess('signed-out'); }
    return () => { current = false; subscription?.unsubscribe(); };
  }, [refresh]);
  const open = (query) => { generation.current++; setDraft(structuredClone(query)); setResult(null); setError(''); };
  const change = (values) => { generation.current++; setDraft((previous) => ({ ...previous, ...values })); setResult(null); };
  const action = async (kind) => {
    const version = ++generation.current;
    setBusy(true); setError('');
    try {
      if (kind === 'run') {
        const data = await adminRequest('/query', { method: 'POST', body: { ...filters, sql: draft.sql } });
        if (generation.current === version) setResult(data);
      } else if (kind === 'delete') {
        await adminRequest(`/queries/${draft.id}?revision=${draft.revision}`, { method: 'DELETE' });
        setDraft(null); setRefresh((value) => value + 1);
      } else {
        const { id, title, sql, visualization, position, revision } = draft;
        const saved = await adminRequest(id ? `/queries/${id}` : '/queries', { method: id ? 'PUT' : 'POST', body: { title, sql, visualization, position, revision } });
        setDraft(saved); setRefresh((value) => value + 1);
      }
    } catch (err) { setError(err.message); } finally { setBusy(false); }
  };
  const signOut = async () => {
    try { const { error: authError } = await getClient().auth.signOut(); if (authError) throw authError; } catch (err) { setError(err.message); }
  };
  const signIn = async () => {
    try { const { error: authError } = await getClient().auth.signInWithOAuth({ provider: 'google', options: { redirectTo: `${window.location.origin}/admin` } }); if (authError) throw authError; } catch (err) { setError(err.message); }
  };
  return <div className="admin-workspace"><SiteHeader product="Admin" to="/admin" icon={<ChartColumn size={22} />}>
    {access === 'allowed' && <button className="cc-button cc-button--ghost" onClick={signOut}>Sign out</button>}
  </SiteHeader><main className="admin-main"><h1>Admin</h1>
    {access !== 'allowed' ? <section className="cc-data-panel admin-card">{access === 'loading' ? <><Skeleton label="Loading admin" />{error && <><p className="cc-notice cc-notice--error" role="alert">{error}</p><button className="cc-button cc-button--secondary" onClick={() => setRefresh((n) => n + 1)}>Retry</button></>}</> : access === 'denied' ? <><p>Access denied</p><button className="cc-button cc-button--ghost" onClick={signOut}>Sign out</button></> : <><button className="cc-button cc-button--secondary" onClick={signIn}>Sign in with Google</button>{error && <p className="cc-notice cc-notice--error" role="alert">{error}</p>}</>}</section> : <>
      <div className="admin-controls"><label>From<input className="cc-input" type="date" value={dates[0]} onChange={(e) => setDates([e.target.value, dates[1]])} /></label><label>To (UTC)<input className="cc-input" type="date" value={dates[1]} onChange={(e) => setDates([dates[0], e.target.value])} /></label><label>Project<select className="cc-select" value={project} onChange={(e) => setProject(e.target.value)}><option value="">All projects</option>{['commons', 'dice', 'trips', 'crowdset', 'fantasy'].map((key) => <option key={key}>{key}</option>)}</select></label><button className="cc-button cc-button--secondary" onClick={() => setRefresh((n) => n + 1)}>Refresh</button><button className="cc-button cc-button--primary" onClick={() => open(blank())}>New query</button></div>
      {!filters && <p className="cc-notice cc-notice--error" role="alert">Choose a date range of 1–366 days.</p>}{error && <p className="cc-notice cc-notice--error" role="alert">{error}</p>}
      {draft && <section className="cc-data-panel admin-card admin-editor"><header><h2>{draft.id ? 'Edit query' : 'New query'}</h2><button className="cc-button cc-button--secondary" disabled={busy} onClick={() => { generation.current++; setDraft(null); }}>Close</button></header><label>Title<input className="cc-input" value={draft.title} onChange={(e) => change({ title: e.target.value })} /></label><label>SQL<textarea className="cc-textarea" spellCheck="false" rows="12" value={draft.sql} onChange={(e) => change({ sql: e.target.value })} /></label><details className="cc-accordion"><summary>Schema & parameters</summary><p>$1 start · $2 end (exclusive) · $3 project (nullable)</p>{catalog ? catalog.views.map((view) => <p key={view.view}><strong>{view.view}</strong>: {view.columns.map((col) => `${col.name} (${col.type})`).join(', ')}</p>) : <p>Catalog unavailable</p>}</details><div className="admin-controls"><SegmentedControl label="View" options={['table', 'line', 'bar'].map((value) => ({ value, label: value[0].toUpperCase() + value.slice(1) }))} value={draft.visualization.type} onChange={(type) => change({ visualization: { ...draft.visualization, type } })} /><label>X column<input className="cc-input" value={draft.visualization.x || ''} onChange={(e) => change({ visualization: { ...draft.visualization, x: e.target.value } })} /></label><label>Y columns<input className="cc-input" value={draft.visualization.y?.join(', ') || ''} onChange={(e) => change({ visualization: { ...draft.visualization, y: e.target.value.split(',').map((s) => s.trim()).filter(Boolean) } })} /></label><label>Series column<input className="cc-input" value={draft.visualization.series || ''} onChange={(e) => change({ visualization: { ...draft.visualization, series: e.target.value } })} /></label><label>Position<input className="cc-input" type="number" min="0" max="10000" value={draft.position} onChange={(e) => change({ position: Number(e.target.value) })} /></label></div><div className="admin-controls"><button className="cc-button cc-button--secondary" disabled={busy || !filters} onClick={() => action('run')}>{busy ? 'Working…' : 'Run'}</button><button className="cc-button cc-button--primary" disabled={busy || !draft.title.trim()} onClick={() => action('save')}>Save</button>{draft.id && <><button className="cc-button cc-button--secondary" disabled={busy} onClick={() => open({ ...draft, id: undefined, title: `${draft.title} copy`, revision: 1 })}>Duplicate</button><button className="cc-button cc-button--destructive" disabled={busy} onClick={() => action('delete')}>Delete</button></>}</div>{result && <><Chart result={result} config={draft.visualization} />{result.truncated && <p>Results truncated</p>}</>}</section>}
      {catalog && <p className="admin-collection">{catalog.collection_started_at ? `Collection since ${new Date(catalog.collection_started_at).toISOString().slice(0, 10)} UTC` : 'No events collected yet'}</p>}
      <div className="admin-definitions"><DataRow title="Metric definitions"><p>Active users: distinct verified accounts with activity. Visits: browser sessions, expiring after 30 minutes without reports. Logged-in and logged-out visits overlap when someone signs in. Daily uniques cannot be added to produce range totals. Tracking begins with this release; earlier history is excluded. Today is partial.</p></DataRow></div>
      {filters && <div className="admin-grid">{queries.map((query) => <QueryCard key={query.id} query={query} filters={filters} onEdit={open} refresh={refresh} />)}</div>}{!queries.length && <p>No saved queries</p>}
    </>}
  </main></div>;
}
