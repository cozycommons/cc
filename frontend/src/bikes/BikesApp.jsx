import React, { useState } from 'react';
import SiteHeader from '../components/SiteHeader.jsx';
import { getUrl } from '../api.js';
import '../../../design/cozy-wabi/components.css';
import './bikes.css';

const HEADLINES = { dock: 'Dock here', wait: 'Wait', ride: 'Ride on', unknown: 'No good option' };

function position() {
  return new Promise((resolve, reject) => {
    if (!navigator.geolocation) reject(new Error('This browser has no location access.'));
    else navigator.geolocation.getCurrentPosition(resolve, () => reject(new Error('Allow location to check docks near you.')),
      { enableHighAccuracy: true, timeout: 15000, maximumAge: 30000 });
  });
}

async function check() {
  const { coords } = await position();
  const query = new URLSearchParams({ lat: coords.latitude.toFixed(5), lng: coords.longitude.toFixed(5) });
  const response = await fetch(`${getUrl()}/bikes/wait-or-ride?${query}`);
  if (response.status === 422) throw new Error('No Citi Bike docks near you.');
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new Error(body?.detail || 'Could not check docks. Try again.');
  return body;
}

function Answer({ result }) {
  const alt = result.alternative;
  return (
    <article className={`cc-card bk-answer bk-answer--${result.decision}`} aria-live="polite">
      <h2 className="cc-h2">{HEADLINES[result.decision]}</h2>
      <p className="cc-body">{result.message}</p>
      <dl className="bk-facts">
        <div><dt>Dock</dt><dd>{result.station}</dd></div>
        <div><dt>Open</dt><dd>{result.open_docks}</dd></div>
        {result.wait_min != null && <div><dt>Usual wait</dt><dd>{Math.max(1, Math.round(result.wait_min))} min</dd></div>}
        {alt && <div><dt>Nearest open</dt><dd>{alt.station}, {alt.open_docks} open, {Math.round(alt.ride_min + alt.walk_min)} min</dd></div>}
      </dl>
    </article>
  );
}

export default function BikesApp() {
  const [state, setState] = useState({ status: 'idle' });
  const run = async () => {
    setState({ status: 'loading' });
    try {
      setState({ status: 'done', result: await check() });
    } catch (error) {
      setState({ status: 'error', message: error.message });
    }
  };
  const shortcutUrl = `${getUrl()}/bikes/wait-or-ride?format=text&lat=…&lng=…`;
  return (
    <div className="bk-page">
      <SiteHeader product="Bikes" to="/bikes" icon="🚲" onSignIn={null} />
      <main className="bk-main">
        <h1 className="cc-h1">Wait or ride?</h1>
        <p className="cc-body bk-lede">At a full Citi Bike dock: wait for a slot, or ride to an open one.</p>
        <button className={`cc-button cc-button--primary${state.status === 'loading' ? ' cc-button--loading' : ''}`}
          type="button" onClick={run} disabled={state.status === 'loading'}>
          {state.status === 'loading' ? 'Checking docks…' : 'Check docks near me'}
        </button>
        {state.status === 'error' && <p className="cc-notice cc-notice--error" role="alert">{state.message}</p>}
        {state.status === 'done' && <Answer result={state.result} />}
        <details className="cc-accordion bk-siri">
          <summary>Siri Shortcut</summary>
          <ol className="cc-body">
            <li>Get Current Location.</li>
            <li>Get Contents of URL, with Latitude and Longitude from the location:<br /><code className="cc-mono">{shortcutUrl}</code></li>
            <li>Speak Text with the contents.</li>
          </ol>
        </details>
        <p className="cc-caption bk-source">Usual waits come from a year of public Citi Bike trips; docks are live.</p>
      </main>
    </div>
  );
}
