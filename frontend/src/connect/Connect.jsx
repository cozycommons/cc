import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import SiteHeader from '../components/SiteHeader.jsx';
import { resolveRuntimeServiceUrl } from '../runtimeConfig.js';
import '../../../design/cozy-wabi/components.css';
import './connect.css';

const PUBLIC_CONNECTOR = 'https://api.cozycommons.dev/mcp';

// Remote agents need a public endpoint, including when this guide runs locally.
export function connectorUrl(configured = import.meta.env.VITE_API_URL) {
  try {
    const url = new URL(resolveRuntimeServiceUrl(configured));
    const host = url.hostname.toLowerCase();
    if (url.protocol !== 'https:' || host === 'localhost' || host.endsWith('.localhost') ||
        host === '[::1]' || host.startsWith('127.') || host === '0.0.0.0' || url.username || url.password) return PUBLIC_CONNECTOR;
    return `${url.origin}/mcp`;
  } catch { return PUBLIC_CONNECTOR; }
}

export default function Connect() {
  const url = connectorUrl();
  const input = useRef(null);
  const [copyState, setCopyState] = useState('');
  useEffect(() => {
    document.body.classList.add('cc-connect-body');
    const previous = document.title;
    document.title = 'Connect your agent · Cozy Commons';
    return () => { document.body.classList.remove('cc-connect-body'); document.title = previous; };
  }, []);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(url);
      setCopyState('Copied');
    } catch {
      input.current.focus();
      input.current.select();
      try {
        if (document.execCommand?.('copy')) { setCopyState('Copied'); return; }
      } catch { /* Keep the URL selected for manual copying. */ }
      setCopyState('URL selected. Copy it with your device’s copy command.');
    }
  };
  return <div className="cc-page cc-connect">
    <SiteHeader />
    <main id="connect-main">
      <h1>Connect your agent</h1>
      <section aria-labelledby="connector-heading" className="cc-connect-endpoint">
        <h2 id="connector-heading">Connector URL</h2>
        <div className="cc-connect-copy"><input ref={input} aria-label="Connector URL" readOnly value={url} onFocus={event => event.target.select()} />
          <button type="button" className="cc-button cc-button--primary" onClick={copy}>{copyState === 'Copied' ? 'Copied' : 'Copy'}</button></div>
        <p role="status" className="cc-connect-status">{copyState}</p>
      </section>
      <section aria-labelledby="client-heading">
        <h2 id="client-heading">Add it to your agent</h2>
        <dl className="cc-connect-clients">
          <div><dt>Claude</dt><dd>Open Settings → Connectors → Add custom connector, then paste the URL. Menu labels may vary; choose a remote/web connector with OAuth and automatic client registration. <a href="https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp">Claude setup</a></dd></div>
          <div><dt>ChatGPT</dt><dd>Enable developer mode where available, then add a custom MCP connector/app with this URL and OAuth. Workspace permissions may require an admin. <a href="https://developers.openai.com/api/docs/guides/custom-mcp-server">ChatGPT setup</a></dd></div>
          <div><dt>Muse</dt><dd>If your version supports remote MCP with OAuth, add a custom/remote MCP connector and paste the URL.</dd></div>
          <div><dt>Grok</dt><dd>If your version supports remote MCP with OAuth, add a custom/remote MCP connector and paste the URL.</dd></div>
          <div><dt>Other MCP clients</dt><dd>Use Streamable HTTP with OAuth, dynamic client registration and PKCE. Clients that only accept pasted API keys or stdio servers cannot use this connector.</dd></div>
        </dl>
        <p>“Grokbot” and “Dots” are unidentified agents. Their compatibility, and exact Muse and Grok setup menus, have not been verified.</p>
      </section>
      <section aria-labelledby="consent-heading">
        <h2 id="consent-heading">Sign in and approve</h2>
        <p>The connector first asks you to approve your agent for two permissions: <code>commons:read</code> to read your data in the projects you enable, and <code>commons:edit</code> to save changes you confirm. Next comes Google sign-in to Cozy Commons. Then <code>/oauth/consent</code> shows “Connect an application,” your account and the application name. Choose “Allow connection” or “Deny.”</p>
        <p>These two permissions cover every Cozy Commons project, so adding a project later never needs a new approval. An agent that requests only <code>commons:read</code> can never make changes.</p>
      </section>
      <section aria-labelledby="tools-heading">
        <h2 id="tools-heading">What your agent can do</h2>
        <p>Ask your agent to call <code>list_projects</code> first. It shows each project, whether it is on for you, and your next step. Projects you already use, such as Trips when you belong to a trip, are on already. Your agent turns others on with <code>enable_project</code> and off with <code>disable_project</code>. Turning a project off hides its tools and keeps its data. If new tools do not appear, refresh the agent’s tool list or reconnect.</p>
        <ul><li><Link to="/trips">Trips</Link>: read balances and settlement links, split expenses, and record repayments already made. It does not send money.</li>
          <li><Link to="/floor-planner">Floor Planner</Link>: read and edit plans you have access to.</li>
          <li>Beli: get restaurant recommendations and save places to your Beli Want to Try list. The first time, your agent links your Beli account with your existing Beli token using <code>link_beli_account</code>; after that you don’t paste the token again.</li>
          <li>Resy: find open tables, list your reservations, and book or cancel real reservations. Bookings and cancellations can charge a deposit or cancellation fee to your card; your agent shows each fee, the policy and the card first. Link once with your existing Resy token using <code>link_resy_account</code>.</li>
          <li>Partiful: read-only. List the events you host, RSVP’d to or were invited to, or read one event’s details. Guest lists are never shared. Link once with your existing Partiful token using <code>link_partiful_account</code>.</li>
          <li>ESPN: read your fantasy basketball league, and set lineups, add and drop players or offer trades for your own team. Every change is proposed first and only sent to ESPN after you approve that exact change. Link once with your existing ESPN token using <code>link_espn_account</code>.</li></ul>
        <p>Writes always need a preview first (<code>dry_run=true</code>) and your confirmation before saving. For trip expenses, review the per-person amounts. For Resy, review the fees and card before you say yes. For ESPN, review the proposed lineup, roster edit or trade offer.</p>
      </section>
      <section aria-labelledby="reconnect-heading">
        <h2 id="reconnect-heading">Connected before projects could be switched on?</h2>
        <p>Connections approved with the older Trips (<code>trips:read</code>, <code>trips:edit</code>) or Floor Planner (<code>floor-plans:read</code>, <code>floor-plans:edit</code>) permissions keep working for those projects. They stop when they expire, at most 30 days after you approved them. Reconnect once to use any other project; your agent will say when you need to.</p>
      </section>
      <section aria-labelledby="disconnect-heading">
        <h2 id="disconnect-heading">Disconnect</h2>
        <p>Open <Link to="/account#agents">Connected agents</Link> on your account and choose Disconnect. That agent’s access stops on its next request, and it must sign in and approve again to reconnect. Also remove the connector in your agent so it stops asking.</p>
        <p>A connection approved before the account page existed shows there after its next use.</p>
      </section>
    </main>
  </div>;
}
