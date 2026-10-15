import React from 'react';
import { endpoint, request } from './api';
import './crowd-set.css';

export function time(seconds) {
  const value = Math.max(0, seconds || 0);
  return `${Math.floor(value / 60)}:${(value % 60).toFixed(1).padStart(4, '0')}`;
}
const accept = '.wav,.mp3,.m4a,.mp4,.mov,.aac,.flac,.ogg,.webm';
const isBusy = (set) => ['processing', 'uploading'].includes(set?.status);

export default function CrowdSet() {
  const [sets, setSets] = React.useState([]);
  const [selected, setSelected] = React.useState(null);
  const [name, setName] = React.useState('');
  const [busy, setBusy] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState('');
  const [notice, setNotice] = React.useState('');
  const [available, setAvailable] = React.useState(false);
  const [needsSignIn, setNeedsSignIn] = React.useState(false);
  const selection = React.useRef(null);
  const local = ['localhost', '127.0.0.1'].includes(window.location.hostname);

  const choose = React.useCallback((value) => {
    selection.current = value?.id || null;
    setSelected(value);
  }, []);
  const update = React.useCallback((value) => {
    setSets((previous) => [value, ...previous.filter((item) => item.id !== value.id)]);
    if (selection.current === value.id) setSelected(value);
  }, []);

  const reload = React.useCallback(async () => {
    setLoading(true);
    setError('');
    try {
      const values = await request();
      setSets(values);
      choose(values.find((item) => item.id === selection.current) || values[0] || null);
      setAvailable(true);
      setNeedsSignIn(false);
    } catch (failure) {
      setAvailable(false);
      setNeedsSignIn(failure.status === 401);
      setError(failure.status === 401 ? '' : local ? `${failure.message}. Start the local Crowd Set API, then reconnect.` : failure.message);
    } finally { setLoading(false); }
  }, [choose, local]);

  React.useEffect(() => { reload(); }, [reload]);
  React.useEffect(() => {
    if (local) return;
    let subscription;
    let stopped = false;
    let timer;
    import('../supabase').then(({ getClient }) => {
      if (stopped) return;
      subscription = getClient().auth.onAuthStateChange((event) => {
        if (event === 'SIGNED_OUT') {
          fetch('/crowd-set/session', { method: 'DELETE' });
          choose(null); setSets([]); setAvailable(false); setNeedsSignIn(true);
        } else if (event === 'TOKEN_REFRESHED' || event === 'SIGNED_IN') {
          clearTimeout(timer);
          timer = setTimeout(reload, 0);
        }
      }).data.subscription;
    });
    return () => { stopped = true; clearTimeout(timer); subscription?.unsubscribe(); };
  }, [choose, local, reload]);
  const selectedId = selected?.id;
  const selectedStatus = selected?.status;
  React.useEffect(() => {
    if (!selectedId || !['processing', 'uploading'].includes(selectedStatus)) return;
    let stopped = false;
    let timer;
    const poll = async () => {
      try {
        const value = await request(`/${selectedId}`);
        if (!stopped) { update(value); setError(''); }
      } catch (failure) {
        if (!stopped) setError(`${failure.message}. Retrying status…`);
      }
      if (!stopped) timer = setTimeout(poll, 1500);
    };
    timer = setTimeout(poll, 1000);
    return () => { stopped = true; clearTimeout(timer); };
  }, [selectedId, selectedStatus, update]);

  async function action(callback) {
    setBusy(true); setError(''); setNotice('');
    try { await callback(); } catch (failure) { setError(failure.message); }
    finally { setBusy(false); }
  }
  async function upload(event, role) {
    const files = Array.from(event.target.files || []);
    event.target.value = '';
    const id = selected.id;
    await action(async () => {
      for (let index = 0; index < files.length; index += 1) {
        const file = files[index];
        if (file.size > 512 * 1024 * 1024) throw new Error(`${file.name} exceeds 512 MiB.`);
        setNotice(`Uploading ${file.name} (${index + 1}/${files.length})…`);
        update(await request(`/${id}/clips?role=${role}&name=${encodeURIComponent(file.name)}`, {
          method: 'PUT', headers: { 'Content-Type': 'application/octet-stream' }, body: file,
        }));
      }
      setNotice('Upload complete.');
    });
  }
  const locked = busy || isBusy(selected);
  const reference = selected?.clips.find((clip) => clip.role === 'reference');
  const crowd = selected?.clips.filter((clip) => clip.role === 'crowd') || [];
  const timeline = selected?.timeline;

  return <main className="crowd-set">
    <header className="cs-header"><a href="/">Cozy Commons</a></header>
    <section className="cs-intro"><h1>Crowd Set</h1></section>
    <>
      {error && <div role="alert" className="cs-error">{error}</div>}
      {loading ? <p role="status">Loading…</p> : !available ? <section className="cs-card"><h2>{needsSignIn ? 'Sign in' : 'Connect to Crowd Set'}</h2>{needsSignIn ? <button onClick={() => action(async () => { const { auth } = await import('../supabase'); await auth.signInWithGoogle(`${window.location.origin}/crowd-set`); })}>Continue with Google</button> : <>{local && <p>Run <code>bash scripts/crowd-set-dev.sh setup</code>, then <code>bash scripts/crowd-set-dev.sh run</code> from this checkout.</p>}<button onClick={reload}>Reconnect</button></>}</section> : <>
        <section className="cs-library cs-card" aria-label="Sets">
          <div><label htmlFor="performance">Set</label><select id="performance" value={selected?.id || ''} disabled={busy} onChange={(event) => { choose(sets.find((item) => item.id === event.target.value)); setError(''); setNotice(''); }}>
            {!sets.length && <option value="">No sets yet</option>}{sets.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}
          </select></div>
          <form onSubmit={(event) => { event.preventDefault(); action(async () => { const value = await request('', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ name: name.trim() }) }); update(value); choose(value); setName(''); }); }}>
            <label htmlFor="set-name">New set</label><div className="cs-inline"><input id="set-name" placeholder="Artist · venue · night" value={name} maxLength={120} onChange={(event) => setName(event.target.value)} /><button disabled={busy || !name.trim()}>Create set</button></div>
          </form>
        </section>
        {selected && <>
          <section className="cs-workspace-heading"><div><h2>{selected.name}</h2></div><button className="cs-subtle" disabled={locked} onClick={() => { if (window.confirm(`Delete “${selected.name}” and its local recordings?`)) action(async () => { await request(`/${selected.id}`, { method: 'DELETE' }); choose(null); await reload(); }); }}>Delete set</button></section>
          <div className="cs-upload-grid">
            <section className="cs-card"><h3>Reference</h3><p>Full recording of this performance. Used for timing only.</p>
              {reference ? <div className="cs-file"><strong>{reference.name}</strong><span>Not included in playback</span><button disabled={locked} onClick={() => action(async () => update(await request(`/${selected.id}/clips/${reference.id}`, { method: 'DELETE' })))}>Remove reference</button></div> : <label className="cs-upload">Upload reference<input aria-label="Upload timing reference" type="file" accept={accept} disabled={locked} onChange={(event) => upload(event, 'reference')} /></label>}
              <small>Up to 2 hours · 512 MiB</small>
            </section>
            <section className="cs-card"><h3>Recordings</h3><p>Up to 8 clips from this performance.</p><label className="cs-upload">Upload recordings<input aria-label="Upload crowd clips" type="file" multiple accept={accept} disabled={locked || crowd.length >= 8} onChange={(event) => upload(event, 'crowd')} /></label><small>37 seconds–20 minutes · 512 MiB each</small></section>
          </div>
          <p className="cs-muted cs-formats">WAV, MP3, M4A, MP4, MOV, AAC, FLAC, OGG, WEBM</p>
          {!!crowd.length && <section className="cs-card"><h3>Recordings</h3><div className="cs-sources">{crowd.map((clip) => <article key={clip.id} className="cs-source">
            <label><input type="checkbox" checked={clip.included} disabled={locked} onChange={(event) => action(async () => update(await request(`/${selected.id}/clips/${clip.id}`, { method: 'PATCH', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ included: event.target.checked }) })))} /><strong>{clip.name}</strong></label>
            <span className={`cs-badge ${clip.alignment?.status || ''}`}>{!clip.included ? 'Excluded' : clip.alignment?.status || 'Ready'}</span>
            <button className="cs-subtle" disabled={locked} onClick={() => action(async () => update(await request(`/${selected.id}/clips/${clip.id}`, { method: 'DELETE' })))}>Remove</button>
            {clip.alignment && <div className="cs-source-detail">{clip.alignment.status === 'matched' ? <p>Starts at {clip.alignment.offset_seconds < 0 ? '−' : ''}{time(Math.abs(clip.alignment.offset_seconds))} · ±{clip.alignment.uncertainty_seconds.toFixed(2)}s</p> : <p>{clip.alignment.reason}</p>}
              {!!clip.alignment.windows.length && <details><summary>Timing details</summary><ul>{clip.alignment.windows.map((window, index) => <li key={index}>{time(window.source_seconds)}: offset {window.offset_seconds}s · similarity {window.similarity} · margin {window.peak_margin}{window.strong ? '' : ' · weak match'}</li>)}</ul></details>}</div>}

          </article>)}</div></section>}
          <section className="cs-process"><button className="cs-primary" disabled={locked || !reference || !crowd.some((clip) => clip.included)} onClick={() => action(async () => update(await request(`/${selected.id}/process`, { method: 'POST' })))}>{isBusy(selected) ? 'Processing…' : selected.status === 'failed' ? 'Retry' : 'Create mix'}</button>
            <p role="status">{busy ? notice || 'Saving…' : selected.status === 'processing' ? 'Processing recordings…' : selected.status === 'failed' ? selected.error : notice || (!reference ? 'Upload a reference to continue.' : !crowd.some((clip) => clip.included) ? 'Add a recording to continue.' : '')}</p></section>
          {timeline && <section className="cs-card cs-result"><h2>{selected.playable ? 'Mix' : 'No recordings matched'}</h2>
            <p>{time(timeline.covered_seconds)} covered of {time(timeline.duration)} · gaps are silence</p>
            <div className="cs-timeline" aria-label="Crowd coverage timeline">{timeline.segments.map((segment, index) => <span key={index} title={`${time(segment.start)}–${time(segment.end)}`} style={{ left: `${segment.start / timeline.duration * 100}%`, width: `${(segment.end - segment.start) / timeline.duration * 100}%` }} />)}</div>
            <div className="cs-scale"><span>0:00</span><span>{time(timeline.duration)}</span></div>
            {selected.playable && <><audio key={`${selected.id}-${selected.clips.map((clip) => clip.id).join('-')}-${selected.status}`} controls preload="metadata" src={endpoint(`/${selected.id}/audio`)} aria-label="Crowd-only reconstruction" /><a className="cs-download" href={endpoint(`/${selected.id}/audio?download=true`)}>Download WAV</a></>}

            {timeline.levels && <details className="cs-levels"><summary>Volume adjustments</summary><ul>{Object.entries(timeline.levels).map(([id, level]) => <li key={id}><strong>{crowd.find((clip) => clip.id === id)?.name}</strong>: {level.gain_db.toFixed(1)} dB · {level.basis.startsWith('Same ') ? 'overlap matched' : 'whole recording'}{level.gain_limited ? ' · gain capped' : ''}</li>)}</ul></details>}
            <div className="cs-intervals"><div><h3>Timeline</h3>{timeline.segments.length ? <ul>{timeline.segments.map((segment, index) => <li key={index}><strong>{time(segment.start)}–{time(segment.end)}</strong> {crowd.find((clip) => clip.id === segment.clip_id)?.name}</li>)}</ul> : <p>Try longer or clearer recordings.</p>}</div><div><h3>Gaps</h3>{timeline.gaps.length ? <ul>{timeline.gaps.map((gap, index) => <li key={index}>{time(gap.start)}–{time(gap.end)} · silence</li>)}</ul> : <p>None</p>}</div></div>
          </section>}
        </>}
      </>}
    </>
  </main>;
}
