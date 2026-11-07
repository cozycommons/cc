import React, { useState } from 'react';
import SiteHeader from '../components/SiteHeader.jsx';
import { getUrl } from '../api.js';
import Explore from './Explore.jsx';
import NearMe from './NearMe.jsx';
import { modeOf, useNeed } from './Mode.jsx';
import Plan from './Plan.jsx';
import { useGeo, usePolling } from './live.js';
import '../../../design/cozy-wabi/components.css';
import './bikes.css';

const TABS = [{ key: 'near', label: 'Map' }, { key: 'plan', label: 'Plan' }, { key: 'explore', label: 'Explore' }];

// A shared map link: /bikes?lat=&lng=&radius=&station= opens the map on that view.
function initialFocus() {
  const query = new URLSearchParams(window.location.search);
  const lat = Number(query.get('lat')), lng = Number(query.get('lng'));
  if (!query.has('lat') || !Number.isFinite(lat) || !Number.isFinite(lng)) return null;
  const radius = Number(query.get('radius'));
  return { lat, lng, radius: Number.isFinite(radius) && radius > 0 ? radius : undefined, station: query.get('station')?.split(',')[0] || null };
}

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
  const [focus] = useState(initialFocus);
  const [planSeed, setPlanSeed] = useState(null);
  const planFrom = (end, station) => { setPlanSeed({ [end]: station }); setTab('plan'); };
  const [need, setNeed] = useNeed();
  const [geo, locate] = useGeo();
  // Where Near me answers from: a searched place, station or dropped pin, else you.
  const [place, setPlace] = useState(null);
  const you = geo.status === 'ready' ? { kind: 'you', name: 'You', lat: geo.lat, lng: geo.lng } : null;
  const origin = place ?? you;
  const locateHere = () => { setPlace(null); locate(); };
  // One live feed for the map and station search; Explore does not need it.
  const live = usePolling('live', {}, tab !== 'explore');
  return (
    <div className={`bk-page${tab === 'near' ? ' is-map' : ''}`} data-mode={modeOf(need)}>
      <SiteHeader product="Bikes" to="/bikes" icon="🚲" onSignIn={null}>
        <nav className="bk-tabs" role="tablist" aria-label="Cozy Bikes">
          {TABS.map((t) => (
            <button key={t.key} type="button" role="tab" className="bk-tab"
              aria-selected={tab === t.key} onClick={() => setTab(t.key)}>{t.label}</button>
          ))}
        </nav>
      </SiteHeader>
      <main className="bk-main">
        {tab === 'near' && (
          <NearMe origin={origin} you={you} geo={geo} locate={locateHere} onOrigin={setPlace} need={need} setNeed={setNeed}
            live={live} focus={focus} onPlan={planFrom} />
        )}
        {tab === 'plan' && <Plan geo={geo} locate={locate} live={live} seed={planSeed} />}
        {tab === 'explore' && <Explore />}
        {tab === 'plan' && <Siri />}
      </main>
    </div>
  );
}
