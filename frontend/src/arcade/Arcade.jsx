import React, {useEffect, useRef, useState} from 'react';
import {useSupabase} from '../contexts/SupabaseContext';
import {getUrl} from '../api';
import './arcade.css';

export default function Arcade() {
  const {supabase} = useSupabase();
  const [session, setSession] = useState(null);
  const [settings, setSettings] = useState(null);
  const [runs, setRuns] = useState([]);
  const [error, setError] = useState('');
  const [launch, setLaunch] = useState(null);
  const [saved, setSaved] = useState(false);
  const [bundle, setBundle] = useState(null);
  const [installing, setInstalling] = useState(false);
  const [finished, setFinished] = useState(false);
  const [launching, setLaunching] = useState(false);
  const launchPending = useRef(false);
  const replay = useRef(null);
  const frame = useRef(null);

  const api = getUrl().replace(/\/$/, '');
  const frameOrigin = new URL(api, location.href).origin;

  async function request(path, method = 'GET', body) {
    const {data} = await supabase.auth.getSession();
    if (!data.session) throw new Error('Sign in to play.');
    const response = await fetch(api + '/arcade/' + path, {
      method, headers: {'Authorization': 'Bearer ' + data.session.access_token, 'Content-Type': 'application/json'},
      ...(body === undefined ? {} : {body: JSON.stringify(body)})
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(typeof data.detail === 'string' ? data.detail : 'Unable to save arcade settings.');
    }
    return response.json();
  }
  useEffect(() => {
    if (!supabase) return;
    supabase.auth.getSession().then(({data}) => setSession(data.session));
    const {data: {subscription}} = supabase.auth.onAuthStateChange((_event, value) => {
      setSession(previous => {
        if (previous?.user.id !== value?.user.id) {setLaunch(null); setSettings(null); setRuns([]); setBundle(null); setFinished(false);}
        return value;
      });
    });
    return () => subscription.unsubscribe();
  }, [supabase]);
  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    Promise.all([request('profile'), request('runs'), request('package')]).then(([profile, history, installed]) => {
      if (!cancelled) {setSettings(profile); setRuns(history); setBundle(installed);}
    }).catch(err => {if (!cancelled) setError(err.message);});
    return () => {cancelled = true;};
  }, [session?.user.id]);
  useEffect(() => {
    const receive = event => {
      if (event.origin !== frameOrigin || event.source !== frame.current?.contentWindow) return;
      if (event.data?.type === 'arcade-ready') {
        if (launch) frame.current.contentWindow.postMessage({type: 'arcade-launch', launch, settings}, frameOrigin);
      }
      if (event.data?.type === 'arcade-result') {
        setFinished(true);
        request('runs').then(setRuns).catch(err => setError(err.message));
      }
      if (event.data?.type === 'arcade-error') setError('The game could not continue. Start a new game to retry.');
    };
    addEventListener('message', receive);
    return () => removeEventListener('message', receive);
  }, [launch, settings, frameOrigin]);
  useEffect(() => {if (finished) replay.current?.focus();}, [finished]);
  async function play() {
    if (launchPending.current) return;
    launchPending.current = true; setLaunching(true);
    setError(''); setSaved(false);
    try {
      const profile = await request('profile', 'PUT', settings);
      setSettings(profile);
      const next = await request('sessions', 'POST');
      setLaunch(next); setFinished(false);
    } catch (err) {setError(err.message);}
    finally {launchPending.current = false; setLaunching(false);}
  }
  async function save() {
    setError('');
    try {await request('profile', 'PUT', settings); setSaved(true);}
    catch (err) {setError(err.message);}
  }
  async function install(file) {
    if (!file) return;
    setInstalling(true); setError('');
    try {
      const {data} = await supabase.auth.getSession();
      const response = await fetch(api + '/arcade/package', {method:'POST',
        headers:{Authorization:'Bearer ' + data.session.access_token, 'Content-Type':'application/gzip'}, body:file});
      const result = await response.json();
      if (!response.ok) throw new Error(result.detail || 'Unable to install the game package.');
      setBundle(await request('package'));
    } catch (err) {setError(err.message);}
    finally {setInstalling(false);}
  }
  function update(name, value) {setSettings(previous => ({...previous, [name]: value})); setSaved(false);}
  return <main className="arcade">
    <header><a href="/">Cozy Commons</a><h1>Arcade</h1><p>Sprint · Clear 40 lines</p></header>
    {error && <p role="alert">{error}</p>}
    {!session ? <button onClick={() => supabase?.auth.signInWithOAuth({provider: 'google', options: {redirectTo: location.href}})}>Sign in to play</button> :
      settings && <>
        {bundle && !bundle.installed && <p role="status">The game package has not been installed.</p>}
        {bundle?.can_install && <label>Install game package <input type="file" accept=".tar.gz,application/gzip" disabled={installing} onChange={event => install(event.target.files[0])}/>{installing && <span role="status">Installing…</span>}</label>}
        <section className="arcade-settings" aria-label="Game settings">
          <label>DAS <select value={settings.das_ms} onChange={e => update('das_ms', Number(e.target.value))}>{[280,200,150,133,120].map(ms => <option key={ms} value={ms}>{ms} ms</option>)}</select></label>
          <label>ARR <select value={settings.arr_ms} onChange={e => update('arr_ms', Number(e.target.value))}>{[50,35,17,7,0].map(ms => <option key={ms} value={ms}>{ms} ms</option>)}</select></label>
          <label>Frame rate <select value={settings.frame_rate} onChange={e => update('frame_rate', Number(e.target.value))}>{[0,60,100,144,240].map(rate => <option key={rate} value={rate}>{rate ? rate + ' fps' : 'Game default'}</option>)}</select></label>
          <label>Keyboard <select value={Object.keys(settings.keys).length ? 'compact' : 'arrows'} onChange={e => update('keys', e.target.value === 'compact' ? {left:'KeyJ',right:'KeyL',soft:'KeyK'} : {})}><option value="compact">HHKB · J / K / L</option><option value="arrows">Arrow keys</option></select></label>
          <label><input type="checkbox" checked={settings.sound} onChange={e => update('sound', e.target.checked)}/>Sound</label>
          <button onClick={save}>Save settings</button>{saved && <span role="status">Saved</span>}
          <button onClick={play} disabled={!bundle?.installed || installing || launching}>{launching ? 'Starting…' : launch ? 'New game' : 'Play'}</button>
        </section>
        <p>Z / X rotate · C hold · Space hard drop. Settings apply to the next game.</p>
        {launch && <div className="arcade-stage">
          <iframe key={launch.id} ref={frame} src={api + '/arcade/frame'} title="Sprint game" sandbox="allow-scripts allow-same-origin" allow="autoplay" />
          {finished && <section className="arcade-finish" aria-label="Run finished">
            <div><h2>Run finished</h2><button ref={replay} className="arcade-replay" onClick={play} disabled={launching}>{launching ? 'Starting…' : 'Play again'}</button></div>
          </section>}
        </div>}
        <section><h2>Recent runs</h2>
          <button onClick={() => request('runs').then(setRuns).catch(err => setError(err.message))}>Refresh runs</button>
          {!runs.length ? <p>No runs yet.</p> : <ul>{runs.map(run => <li key={run.id}>{new Date(run.started_at * 1000).toLocaleString()} · {run.complete ? 'Recorded' : 'Started'}{run.complete && <> · {run.metrics.lines ?? 0} / 40 lines{run.metrics.elapsed_ms != null && <> · {(run.metrics.elapsed_ms / 1000).toFixed(1)} s</>}</>}</li>)}</ul>}
        </section>
      </>}
  </main>;
}
