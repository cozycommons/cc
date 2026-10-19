import React from 'react';
import { ArrowLeft, Plus, Search, Music2, Download } from 'lucide-react';
import { endpoint, request, getLimits } from './api';
import { uploadRecording } from './uploads';
import MixTimeline, { recordingColor } from './MixTimeline';
import CreateSet from './CreateSet';
import { eventDate, eventRange, matchesSearch } from './setDetails';
import './crowd-set.css';

export function time(seconds) {
  const value = Math.max(0, seconds || 0);
  return `${Math.floor(value / 60)}:${(value % 60).toFixed(1).padStart(4, '0')}`;
}
const accept = '.wav,.mp3,.m4a,.mp4,.mov,.aac,.flac,.ogg,.webm';
const isBusy = (set) => ['processing', 'uploading'].includes(set?.status);
const legacyLimits = { recordings: 8, file_bytes: 512 * 1024 ** 2, recording_seconds: 1200, resumable_uploads: false };

export default function CrowdSet() {
  const [sets, setSets] = React.useState([]);
  const [selected, setSelected] = React.useState(null);
  const [creating, setCreating] = React.useState(false);
  const [query, setQuery] = React.useState('');
  const [failedFiles, setFailedFiles] = React.useState([]);
  const [busy, setBusy] = React.useState(false);
  const [loading, setLoading] = React.useState(true);
  const [error, setError] = React.useState('');
  const [statusError, setStatusError] = React.useState('');
  const [notice, setNotice] = React.useState('');
  const [available, setAvailable] = React.useState(false);
  const [needsSignIn, setNeedsSignIn] = React.useState(false);
  const [limits, setLimits] = React.useState(legacyLimits);
  const selection = React.useRef(null);
  const player = React.useRef(null);
  const [currentTime, setCurrentTime] = React.useState(0);
  const local = ['localhost', '127.0.0.1'].includes(window.location.hostname);

  const choose = React.useCallback((value) => {
    selection.current = value?.id || null;
    setSelected(value);
    setStatusError('');
    setCreating(false);
    setFailedFiles([]);
    setError('');
    setCurrentTime(0);
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
      const activeLimits = await getLimits().catch(() => null);
      if (activeLimits?.recordings) setLimits(activeLimits);
      setSets(values);
      choose(values.find((item) => item.id === selection.current) || null);
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
    if (!selectedId || !['processing', 'uploading', 'queued'].includes(selectedStatus)) return;
    let stopped = false;
    let timer;
    const poll = async () => {
      try {
        const value = await request(`/${selectedId}`);
        if (!stopped) { update(value); setStatusError(''); }
      } catch (failure) {
        if (!stopped) setStatusError(`${failure.message}. Retrying status…`);
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
  async function upload(files) {
    const id = selected.id;
    if (!files.length) return;
    setFailedFiles(files);
    await action(async () => {
      const batch = files.length > 1 ? await request(`/${id}/batches`, { method: 'POST' }) : null;
      const failures = [];
      try {
        for (let index = 0; index < files.length; index += 1) {
          const file = files[index];
          setNotice(`Uploading ${file.name} (${index + 1}/${files.length})…`);
          try {
            if (file.size > limits.file_bytes) throw new Error(`Exceeds ${Math.round(limits.file_bytes / 1024 ** 2)} MiB.`);
            update(await uploadRecording(id, file, { batchId: batch?.id, limits,
              onProgress: (uploaded, total) => setNotice(`Uploading ${file.name} (${index + 1}/${files.length}) · ${Math.round(uploaded / total * 100)}%…`),
            }));
            setFailedFiles((previous) => previous.filter((pending) => pending !== file));
          } catch (failure) { failures.push(`${file.name}: ${failure.message}`); }
        }
      } finally {
        setNotice('');
        if (batch) {
          try { update(await request(`/${id}/batches/${batch.id}/finish`, { method: 'POST' })); }
          catch (failure) { failures.push(`Could not finish the upload batch: ${failure.message}. Added files are retained; reconnect to check their status.`); }
        }
      }
      if (failures.length) throw new Error(`Some uploads failed. ${failures.join(' ')} Retry these files; successful uploads are retained.`);
    });
  }
  const locked = busy || isBusy(selected);
  const recordings = selected?.clips || [];
  const ordinary = recordings.filter((clip) => clip.role !== 'reference');
  const used = new Set([...(selected?.timeline?.segments || []), ...(selected?.video_timeline?.segments || [])].map((segment) => segment.clip_id));
  const updating = ['queued', 'processing', 'uploading'].includes(selected?.status);
  const visibleSets = sets.filter((set) => matchesSearch(set, query));
  const contributors = new Set(recordings.map((clip) => clip.uploader).filter(Boolean)).size;

  async function createSet(value) {
    await action(async () => {
      const created = await request('', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(value) });
      update(created); choose(created); setQuery('');
    });
  }

  return <main className="crowd-set">
    <div className="cs-shell">
    <header className="cs-header"><button className="cs-wordmark" disabled={busy} onClick={() => { choose(null); setQuery(''); }}>crowdset</button><a href="/">Cozy Commons ↗</a></header>
    {(error || statusError) && <div role="alert" className="cs-error">{error || statusError}</div>}
    {loading ? <p className="cs-loading" role="status">Loading…</p> : !available ? <section className="cs-sign-in"><h1>{needsSignIn ? 'Sign in' : 'Crowdset'}</h1>
      {needsSignIn ? <button className="cs-primary" disabled={busy} onClick={() => action(async () => { const { auth } = await import('../supabase'); await auth.signInWithGoogle(`${window.location.origin}/crowd-set`); })}>{busy ? 'Connecting…' : 'Continue with Google'}</button> : <button className="cs-primary" onClick={reload}>Reconnect</button>}
    </section> : creating ? <CreateSet sets={sets} structured={limits.event_metadata === true} busy={busy} onCreate={createSet} onChoose={choose} onBack={() => setCreating(false)} /> : !selected ? <>
      <div className="cs-title cs-catalog-title"><h1>Sets</h1><button className="cs-primary cs-new-button" onClick={() => { setCreating(true); setError(''); }}><Plus size={17} /> New set</button></div>
      <label className="cs-search"><Search size={18} aria-hidden="true" /><input type="search" aria-label="Find a set" placeholder="Artist, venue, or date" value={query} onChange={(event) => setQuery(event.target.value)} /></label>
      <section aria-label="Sets" className="cs-set-list">
        {visibleSets.length ? visibleSets.map((item) => <button className="cs-set" key={item.id} onClick={() => { choose(item); setNotice(''); }}>
          <div className="cs-set-cover"><span className="cs-set-date">{eventDate(item) || (item.visibility === 'shared' ? 'Public' : 'Private')}</span><strong>{item.artist || item.name}</strong><span>{item.venue}</span></div>
          <div className="cs-set-footer"><span>{item.clips.length} {item.clips.length === 1 ? 'clip' : 'clips'}{item.timeline?.duration ? ` · ${time(item.timeline.duration)}${item.video_playable ? '' : ' audio'}` : ''}</span><span>{item.video_playable ? 'Watch →' : item.playable ? 'Listen →' : ['processing', 'queued', 'uploading'].includes(item.status) ? 'Processing' : item.clips.length ? 'Open →' : 'Add clips →'}</span></div>
        </button>) : <p className="cs-empty-catalog">{query ? 'No sets found.' : 'No sets yet.'}</p>}
      </section>
    </> : <>
      <button className="cs-back" disabled={busy} onClick={() => { choose(null); reload(); }}><ArrowLeft size={17} /> All sets</button>
      <div className="cs-detail-title"><h1>{selected.artist || selected.name}</h1>{selected.venue && <p>{selected.venue}</p>}{eventRange(selected) && <p className="cs-meta">{eventRange(selected)}</p>}{selected.visibility !== 'shared' && <span className="cs-privacy">Private</span>}</div>
      <section className={`cs-mix ${selected.playable ? 'cs-mix-ready' : ''}`} aria-label="Compiled mix">
        {selected.playable ? <div className="cs-audio-surface">
          <div className="cs-inline"><span>{selected.video_playable ? 'The cut' : 'Audio mix'}</span><div>
            {selected.video_playable && <a aria-label="Download video" href={endpoint(`/${selected.id}/video?download=true&v=${selected.mix_revision}`)}><Download size={18} /> Video</a>}
            <a aria-label="Download audio" href={endpoint(`/${selected.id}/audio?download=true&v=${selected.mix_revision || 'legacy'}`)}><Download size={18} /> Audio</a>
          </div></div>
          {selected.video_playable ? <video ref={player} onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)} onLoadedMetadata={() => setCurrentTime(0)} key={`${selected.id}-${selected.mix_revision}`} controls playsInline preload="metadata" src={endpoint(`/${selected.id}/video?v=${selected.mix_revision}`)} aria-label="Current cut" /> : <>
            <Music2 className="cs-audio-icon" size={40} strokeWidth={1} aria-hidden="true" />
            <audio ref={player} onTimeUpdate={(event) => setCurrentTime(event.currentTarget.currentTime)} onLoadedMetadata={() => setCurrentTime(0)} key={`${selected.id}-${selected.mix_revision || 'legacy'}`} controls preload="metadata" src={endpoint(`/${selected.id}/audio?v=${selected.mix_revision || 'legacy'}`)} aria-label="Current mix" />
          </>}
        </div> : <div className="cs-empty-player"><Music2 size={30} strokeWidth={1.3} aria-hidden="true" /><p>{updating ? 'Processing' : recordings.length ? 'No mix yet.' : 'No clips yet.'}</p></div>}
        {selected.playable && selected.timeline && <MixTimeline timeline={selected.video_playable ? selected.video_timeline : selected.timeline} video={selected.video_playable} clips={recordings} currentTime={currentTime} onSeek={(seconds) => { if (player.current) player.current.currentTime = seconds; setCurrentTime(seconds); }} />}
        <p role="status">{busy ? notice || 'Saving…' : selected.status === 'queued' ? 'Mix queued…' : selected.status === 'uploading' ? 'Uploading recordings…' : selected.status === 'processing' ? selected.stage || 'Updating mix…' : selected.status === 'failed' ? selected.error : selected.dirty ? 'Mix needs an update.' : ''}</p>
        {selected.upload_notice && <p role="status">{selected.upload_notice}</p>}
        {!updating && (selected.status === 'failed' || selected.dirty || (!selected.playable && ordinary.length > 0)) && <button disabled={locked || !ordinary.some((clip) => clip.included)} onClick={() => action(async () => update(await request(`/${selected.id}/process`, { method: 'POST' })))}>{selected.status === 'failed' ? 'Retry' : 'Update mix'}</button>}
        {!busy && failedFiles.length > 0 && <button disabled={locked} onClick={() => upload(failedFiles)}>Retry {failedFiles.length} {failedFiles.length === 1 ? 'upload' : 'uploads'}</button>}
      </section>
      <section aria-label="Recordings">
        <div className="cs-recording-heading"><h2>Clips <span>{recordings.length}{contributors > 0 ? ` · ${contributors} ${contributors === 1 ? 'contributor' : 'contributors'}` : ''}</span></h2>
          <label className={`cs-upload ${!recordings.length ? 'cs-primary' : ''}`}><Plus size={17} /> Add clips<input aria-label="Add clips" type="file" multiple accept={accept} disabled={locked || ordinary.length >= limits.recordings} onChange={(event) => { const files = Array.from(event.target.files || []); event.target.value = ''; upload(files); }} /></label>
        </div>
        <details className="cs-upload-limits"><summary>Upload limits</summary><p className="cs-limits">Up to {limits.recordings} clips · {limits.recording_seconds / 60} minutes and {Math.round(limits.file_bytes / 1024 ** 2)} MiB each · Video or audio</p>{limits.free_tier && <p className="cs-limits">{limits.original_bytes / 1e9} GB total storage across all sets.</p>}</details>
        <div className="cs-recordings">{recordings.map((clip) => <article id={`recording-${clip.id}`} key={clip.id} className="cs-recording" style={{ borderTopColor: recordingColor(clip.id, recordings) }}>
          <Original clip={clip} setId={selected.id} />
          <div className="cs-recording-info"><h3>{clip.name}</h3>
            {clip.uploader_name && <p className="cs-meta">{clip.uploader_name}</p>}
            <p className="cs-meta">{clip.duration ? `${time(clip.duration)} · ` : ''}{clip.bytes ? `${(clip.bytes / 1024 / 1024).toFixed(1)} MB` : ''}</p>
            <p className="cs-clip-status">{used.has(clip.id) ? 'In current mix' : clip.role === 'reference' ? 'Original only' : !clip.included ? 'Not used in mix' : clip.alignment?.status === 'unmatched' ? 'Couldn’t match this recording.' : clip.alignment?.status === 'matched' ? 'Matched · not selected' : clip.alignment?.status === 'error' ? 'Couldn’t use this recording. Try another file.' : updating ? 'Waiting for mix' : 'Not used in mix'}</p>
            <div className="cs-recording-actions"><a href={endpoint(`/${selected.id}/clips/${clip.id}/media?download=true`)}>Download original</a>
              {clip.can_edit && <button disabled={locked} onClick={() => action(async () => update(await request(`/${selected.id}/clips/${clip.id}`, { method: 'DELETE' })))}>Remove</button>}
            </div>
          </div>
        </article>)}</div>
      </section>
      {selected.can_manage && <button className="cs-delete" disabled={locked} onClick={() => { if (window.confirm(`Delete “${selected.name}” and its recordings?`)) action(async () => { await request(`/${selected.id}`, { method: 'DELETE' }); choose(null); await reload(); }); }}>Delete set</button>}
    </>}
    </div>
  </main>;
}

function Original({ clip, setId }) {
  const [failed, setFailed] = React.useState(false);
  const Media = clip.kind === 'video' ? 'video' : 'audio';
  return <div className={`cs-original ${clip.kind === 'video' ? '' : 'cs-original-audio'}`}>
    <Media controls playsInline preload="none" src={endpoint(`/${setId}/clips/${clip.id}/media`)} aria-label={`Play ${clip.name}`} onError={() => setFailed(true)} />
    {failed && <p>Can’t play this format here. Download the original below.</p>}
  </div>;
}
