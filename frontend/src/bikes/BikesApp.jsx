import React, { useState } from 'react';
import SiteHeader from '../components/SiteHeader.jsx';
import { getUrl } from '../api.js';
import Explore from './Explore.jsx';
import NearMe from './NearMe.jsx';
import Plan from './Plan.jsx';
import { useGeo, usePolling } from './live.js';
import '../../../design/cozy-wabi/components.css';
import './bikes.css';

const TABS = [{ key: 'near', label: 'Near me' }, { key: 'plan', label: 'Plan' }, { key: 'explore', label: 'Explore' }];

function initialTab() {
  const tab = new URLSearchParams(window.location.search).get('tab');
  return TABS.some((t) => t.key === tab) ? tab : 'near';
}

function Siri() {
  return (
    <details className="cc-accordion bk-siri">
      <summary>Siri Shortcut</summary>
      <ol className="cc-body">
        <li>Get Current Location.</li>
        <li>Get Contents of URL, with Latitude and Longitude from the location:<br />
          <code className="cc-mono">{`${getUrl()}/bikes/wait?format=text&lat=…&lng=…`}</code></li>
        <li>Speak Text with the contents. Add <code className="cc-mono">&need=dock</code> for a version that finds a dock.</li>
      </ol>
    </details>
  );
}

export default function BikesApp() {
  const [tab, setTab] = useState(initialTab);
  const [need, setNeed] = useState('bike');
  const [geo, locate] = useGeo();
  // One live feed for the map and station search; Explore does not need it.
  const live = usePolling('live', {}, tab !== 'explore');
  return (
    <div className="bk-page">
      <SiteHeader product="Bikes" to="/bikes" icon="🚲" onSignIn={null} />
      <main className="bk-main">
        <nav className="cc-segmented bk-tabs" role="tablist" aria-label="Cozy Bikes">
          {TABS.map((t) => (
            <button key={t.key} type="button" role="tab" className="cc-segmented__item"
              aria-selected={tab === t.key} onClick={() => setTab(t.key)}>{t.label}</button>
          ))}
        </nav>
        {tab === 'near' && (geo.status === 'ready' ? (
          <NearMe geo={geo} need={need} setNeed={setNeed} live={live} />
        ) : (
          <section className="bk-pane bk-start" aria-label="Near me">
            <h1 className="cc-h1">Bikes near you</h1>
            <p className="cc-body">Live bikes, e-bikes and docks at the closest Citi Bike stations, and the odds they are still there when you arrive.</p>
            <button type="button" className="cc-button cc-button--primary" onClick={locate} disabled={geo.status === 'locating'}>
              {geo.status === 'locating' ? 'Finding you…' : 'Use my location'}
            </button>
            {geo.status === 'error' && <p className="cc-notice cc-notice--error" role="alert">{geo.message}</p>}
          </section>
        ))}
        {tab === 'plan' && <Plan geo={geo} locate={locate} live={live} />}
        {tab === 'explore' && <Explore />}
        {tab !== 'explore' && <Siri />}
      </main>
    </div>
  );
}
