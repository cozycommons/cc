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
        if (previous?.user.id !== value?.user.id) {setLaunch(null); setSettings(null); setRuns([]);}
        return value;
      });
    });
    return () => subscription.unsubscribe();
  }, [supabase]);
  useEffect(() => {
    if (!session) return;
    let cancelled = false;
    Promise.all([request('profile'), request('runs')]).then(([profile, history]) => {
      if (!cancelled) {setSettings(profile); setRuns(history);}
    }).catch(err => {if (!cancelled) setError(err.message);});
    return () => {cancelled = true;};
  }, [session?.user.id]);
  useEffect(() => {
    const receive = event => {
      if (event.origin !== frameOrigin || event.source !== frame.current?.contentWindow) return;
      if (event.data?.type === 'arcade-ready') {
        if (launch) frame.current.contentWindow.postMessage({type: 'arcade-launch', launch, settings}, frameOrigin);
      }
      if (event.data?.type === 'arcade-result') request('runs').then(setRuns).catch(err => setError(err.message));
      if (event.data?.type === 'arcade-error') setError('The game could not continue. Start a new game to retry.');
    };
    addEventListener('message', receive);
    return () => removeEventListener('message', receive);
  }, [launch, settings, frameOrigin]);
  async function play() {
    setError(''); setSaved(false);
    try {
      const profile = await request('profile', 'PUT', settings);
      setSettings(profile);
      setLaunch(await request('sessions', 'POST'));
    } catch (err) {setError(err.message);}
  }
  async function save() {
    setError('');
    try {await request('profile', 'PUT', settings); setSaved(true);}
    catch (err) {setError(err.message);}
  }
  function update(name, value) {setSettings(previous => ({...previous, [name]: value})); setSaved(false);}
  return <main className="arcade">
    <header><a href="/">Cozy Commons</a><h1>Arcade</h1><p>Sprint · Clear 40 lines</p></header>
    {error && <p role="alert">{error}</p>}
    {!session ? <button onClick={() => supabase?.auth.signInWithOAuth({provider: 'google', options: {redirectTo: location.href}})}>Sign in to play</button> :
      settings && <>
        <section className="arcade-settings" aria-label="Game settings">
          <label>DAS <select value={settings.das_ms} onChange={e => update('das_ms', Number(e.target.value))}>{[280,200,150,133,120].map(ms => <option key={ms} value={ms}>{ms} ms</option>)}</select></label>
          <label>ARR <select value={settings.arr_ms} onChange={e => update('arr_ms', Number(e.target.value))}>{[50,35,17,7,0].map(ms => <option key={ms} value={ms}>{ms} ms</option>)}</select></label>
          <label>Keyboard <select value={Object.keys(settings.keys).length ? 'compact' : 'arrows'} onChange={e => update('keys', e.target.value === 'compact' ? {left:'KeyJ',right:'KeyL',soft:'KeyK'} : {})}><option value="compact">HHKB · J / K / L</option><option value="arrows">Arrow keys</option></select></label>
          <label><input type="checkbox" checked={settings.sound} onChange={e => update('sound', e.target.checked)}/>Sound</label>
          <button onClick={save}>Save settings</button>{saved && <span role="status">Saved</span>}
          <button onClick={play}>{launch ? 'New game' : 'Play'}</button>
        </section>
        <p>Z / X rotate · C hold · Space hard drop. Settings apply to the next game.</p>
        {launch && <iframe key={launch.id} ref={frame} src={api + '/arcade/frame'} title="Sprint game" sandbox="allow-scripts allow-same-origin" allow="autoplay" />}
        <section><h2>Recent runs</h2>
          <button onClick={() => request('runs').then(setRuns).catch(err => setError(err.message))}>Refresh runs</button>
          {!runs.length ? <p>No runs yet.</p> : <ul>{runs.map(run => <li key={run.id}>{new Date(run.started_at * 1000).toLocaleString()} · {run.complete ? 'Recorded' : 'Started'}{run.complete && <> · {run.metrics.lines ?? 0} / 40 lines{run.metrics.elapsed_ms != null && <> · {(run.metrics.elapsed_ms / 1000).toFixed(1)} s</>}</>}</li>)}</ul>}
        </section>
      </>}
  </main>;
}
