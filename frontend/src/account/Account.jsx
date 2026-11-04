import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useLocation } from 'react-router-dom';
import SiteHeader from '../components/SiteHeader.jsx';
import PlayerAvatar from '../dice/components/PlayerAvatar.jsx';
import { AVATAR_IMAGE_MAX_EDGE, compactImage, uniqueImageFolder } from '../dice/imageUpload.js';
import { connectorUrl } from '../connect/Connect.jsx';
import {
  accountRequest, commonsSupabase, showCommonsProfile, signInToCommons, useCommonsIdentity,
} from '../components/commonsIdentity.js';
import '../../../design/cozy-wabi/components.css';
import './account.css';

// Avatars share Dice's bucket and `<uid>/` policy, so a photo set here is the Dice photo too.
const AVATAR_BUCKET = 'dice-profile-photos';

const day = (value) => (value ? new Date(value).toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' }) : '');

function Profile({ profile }) {
  const [name, setName] = useState(profile.display_name);
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState('');
  const [error, setError] = useState('');
  useEffect(() => { if (!editing) setName(profile.display_name); }, [profile.display_name, editing]);

  const save = async (changes, what) => {
    setBusy(what); setError('');
    try {
      showCommonsProfile(await accountRequest('/profile', { method: 'PATCH', body: changes }));
      return true;
    } catch (err) {
      setError(err.message);
      return false;
    } finally { setBusy(''); }
  };
  const saveName = async (event) => {
    event.preventDefault();
    if (await save({ display_name: name.trim() }, 'name')) setEditing(false);
  };
  const uploadPhoto = async (event) => {
    const file = event.target.files?.[0];
    event.target.value = '';
    if (!file) return;
    setBusy('photo'); setError('');
    try {
      const supabase = commonsSupabase();
      const image = await compactImage(file, { maxEdge: AVATAR_IMAGE_MAX_EDGE, quality: 0.8 });
      const path = `${uniqueImageFolder(profile.user_id)}/avatar.webp`;
      const { error: uploadError } = await supabase.storage.from(AVATAR_BUCKET)
        .upload(path, image, { contentType: 'image/webp', cacheControl: '31536000', upsert: false });
      if (uploadError) throw uploadError;
      const { data } = supabase.storage.from(AVATAR_BUCKET).getPublicUrl(path);
      await save({ avatar_url: data.publicUrl }, 'photo');
    } catch (err) {
      setError(/^(Use a |Image must|That image|This browser)/.test(err?.message || '') ? err.message : 'Could not upload that photo.');
      setBusy('');
    }
  };

  return <section aria-labelledby="profile-heading" className="cc-account-section">
    <h2 id="profile-heading">Profile</h2>
    <div className="cc-account-profile">
      <PlayerAvatar profile={profile} size={72} linkToProfile={false} />
      <div className="cc-account-profile-fields">
        {editing ? <form onSubmit={saveName} className="cc-account-name-form">
          <input className="cc-input" aria-label="Display name" autoFocus required maxLength={80} value={name} onChange={(event) => setName(event.target.value)} />
          <button type="submit" className="cc-button cc-button--primary" disabled={busy !== '' || !name.trim()}>{busy === 'name' ? 'Saving…' : 'Save'}</button>
          <button type="button" className="cc-button cc-button--ghost" disabled={busy === 'name'} onClick={() => setEditing(false)}>Cancel</button>
        </form> : <p className="cc-account-name"><strong>{profile.display_name}</strong>
          <button type="button" className="cc-button cc-button--ghost" onClick={() => setEditing(true)}>Edit name</button></p>}
        {profile.email && <p className="cc-account-muted">{profile.email}</p>}
        <div className="cc-account-photo">
          <label className="cc-button cc-button--secondary" aria-disabled={busy !== '' || undefined}>
            {busy === 'photo' ? 'Uploading…' : 'Change photo'}
            <input type="file" accept="image/jpeg,image/png,image/webp" disabled={busy !== ''} onChange={uploadPhoto} />
          </label>
          {profile.avatar_url && <button type="button" className="cc-button cc-button--ghost" disabled={busy !== ''} onClick={() => save({ avatar_url: null }, 'photo')}>Remove photo</button>}
        </div>
        {error && <p className="cc-notice cc-notice--error" role="alert">{error}</p>}
      </div>
    </div>
    <p className="cc-account-muted">Your name and photo show in every Cozy Commons project.</p>
  </section>;
}

function Connection({ connection, onDisconnect }) {
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const name = connection.client_name || 'Unnamed agent';
  const disconnect = async () => {
    setBusy(true); setError('');
    try { await onDisconnect(connection.id); } catch (err) { setError(err.message); setBusy(false); }
  };
  const edits = (connection.scopes || []).includes('commons:edit');
  return <li className="cc-account-connection">
    <div>
      <strong>{name}</strong>{connection.redirect_host && <span className="cc-account-muted"> · {connection.redirect_host}</span>}
      <p className="cc-account-muted">{edits ? 'Read and save changes' : 'Read only'} · Connected {day(connection.approved_at)}{connection.last_used_at ? ` · Used ${day(connection.last_used_at)}` : ''}</p>
      {error && <p className="cc-notice cc-notice--error" role="alert">{error}</p>}
    </div>
    {confirming
      ? <div className="cc-account-confirm" role="group" aria-label={`Disconnect ${name}?`}>
        <button type="button" className="cc-button cc-button--destructive" disabled={busy} onClick={disconnect}>{busy ? 'Disconnecting…' : `Disconnect ${name}`}</button>
        <button type="button" className="cc-button cc-button--ghost" disabled={busy} onClick={() => setConfirming(false)}>Cancel</button>
      </div>
      : <button type="button" className="cc-button cc-button--secondary" onClick={() => setConfirming(true)}>Disconnect</button>}
  </li>;
}

function Agents() {
  const url = connectorUrl();
  const [connections, setConnections] = useState(null);
  const [error, setError] = useState('');
  const [copied, setCopied] = useState('');
  const load = useCallback(async () => {
    setError('');
    try { setConnections(await accountRequest('/connections')); } catch (err) { setError(err.message); setConnections([]); }
  }, []);
  useEffect(() => { load(); }, [load]);
  const disconnect = async (id) => {
    await accountRequest(`/connections/${id}`, { method: 'DELETE' });
    setConnections((current) => current.filter((connection) => connection.id !== id));
  };
  const copy = async () => {
    try { await navigator.clipboard.writeText(url); setCopied('Copied'); } catch { setCopied('Select the URL and copy it.'); }
  };

  return <section aria-labelledby="agents-heading" id="agents" className="cc-account-section">
    <h2 id="agents-heading">Connected agents</h2>
    <p>Add this URL to Claude, ChatGPT or any MCP client with OAuth. One connection covers every project. <Link to="/connect">Setup steps</Link></p>
    <div className="cc-account-copy">
      <input className="cc-input" aria-label="Connector URL" readOnly value={url} onFocus={(event) => event.target.select()} />
      <button type="button" className="cc-button cc-button--primary" onClick={copy}>{copied === 'Copied' ? 'Copied' : 'Copy'}</button>
    </div>
    <p role="status" className="cc-account-muted cc-account-status">{copied}</p>
    {error && <p className="cc-notice cc-notice--error" role="alert">{error} <button type="button" className="cc-button cc-button--ghost" onClick={load}>Retry</button></p>}
    {connections === null ? <p role="status" className="cc-account-muted">Loading connections…</p>
      : connections.length ? <ul className="cc-account-connections">{connections.map((connection) =>
        <Connection key={connection.id} connection={connection} onDisconnect={disconnect} />)}</ul>
        : !error && <p className="cc-account-muted">No agents connected.</p>}
    <p className="cc-account-muted">Agent names are reported by the agent itself; the host beside each one shows where it signs in.</p>
  </section>;
}

function BeliAccount({ account, openOnLoad, onConnected }) {
  const [open, setOpen] = useState(openOnLoad && !account);
  const [login, setLogin] = useState('');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const row = useRef(null);
  // The page's own hash scroll runs before this row exists, so the agent's #beli link lands here.
  useEffect(() => { if (openOnLoad) row.current?.scrollIntoView?.(); }, [openOnLoad]);
  const close = () => { setOpen(false); setPassword(''); setError(''); };
  const submit = async (event) => {
    event.preventDefault();
    setBusy(true); setError('');
    try {
      const result = await accountRequest('/linked-accounts/beli', { method: 'POST', body: { login: login.trim(), password } });
      onConnected(result.account);
      setLogin(''); close();
    } catch (err) { setError(err.message); } finally { setBusy(false); setPassword(''); }
  };
  return <li className="cc-account-connection" id="beli" ref={row}>
    <div>
      <strong>Beli</strong>
      <p className="cc-account-muted">{account ? 'Connected' : 'Not connected'}</p>
      {open && <form className="cc-account-login" onSubmit={submit}>
        <input className="cc-input" aria-label="Beli email or phone" placeholder="Beli email or phone" autoComplete="username"
          required maxLength={200} value={login} onChange={(event) => setLogin(event.target.value)} />
        <input className="cc-input" type="password" aria-label="Beli password" placeholder="Beli password" autoComplete="current-password"
          required maxLength={200} value={password} onChange={(event) => setPassword(event.target.value)} />
        <div className="cc-account-confirm">
          <button type="submit" className="cc-button cc-button--primary" disabled={busy || !login.trim() || !password}>
            {busy ? 'Checking with Beli…' : account ? 'Save password' : 'Connect Beli'}</button>
          <button type="button" className="cc-button cc-button--ghost" disabled={busy} onClick={close}>Cancel</button>
        </div>
        <p className="cc-account-muted">Stored encrypted and used only for your Beli requests.</p>
      </form>}
      {error && <p className="cc-notice cc-notice--error" role="alert">{error}</p>}
    </div>
    {!open && <button type="button" className="cc-button cc-button--secondary" onClick={() => setOpen(true)}>
      {account ? 'Update password' : 'Connect'}</button>}
  </li>;
}

function LinkedAccounts({ hash }) {
  const [linked, setLinked] = useState(null);
  const [error, setError] = useState('');
  const load = useCallback(async () => {
    setError('');
    try { setLinked(await accountRequest('/linked-accounts')); } catch (err) { setError(err.message); }
  }, []);
  useEffect(() => { load(); }, [load]);

  return <section aria-labelledby="linked-heading" id="linked-accounts" className="cc-account-section">
    <h2 id="linked-heading">Linked accounts</h2>
    <p>Agents use these through your Cozy Commons connection. Enter passwords here, never in an agent chat.</p>
    {error && <p className="cc-notice cc-notice--error" role="alert">{error} <button type="button" className="cc-button cc-button--ghost" onClick={load}>Retry</button></p>}
    {linked === null ? !error && <p role="status" className="cc-account-muted">Loading linked accounts…</p>
      : <ul className="cc-account-connections">
        <BeliAccount account={linked.beli} openOnLoad={hash === '#beli'}
          onConnected={(account) => setLinked((current) => ({ ...current, beli: account }))} />
      </ul>}
  </section>;
}

export default function Account() {
  const { status, profile } = useCommonsIdentity();
  const { hash } = useLocation();
  const [error, setError] = useState('');
  const scrolled = useRef('');
  useEffect(() => {
    document.body.classList.add('cc-account-body');
    const previous = document.title;
    document.title = 'Account · Cozy Commons';
    return () => { document.body.classList.remove('cc-account-body'); document.title = previous; };
  }, []);
  useEffect(() => {
    if (status !== 'signed-in' || !hash || scrolled.current === hash) return;
    scrolled.current = hash;
    document.getElementById(hash.slice(1))?.scrollIntoView?.();
  }, [status, hash]);
  const signIn = async () => {
    setError('');
    try { await signInToCommons(); } catch (err) { setError(err?.message || 'Could not start sign-in.'); }
  };

  return <div className="cc-page cc-account-page">
    <SiteHeader product="Account" to="/account" onSignIn={null} />
    <main id="account-main">
      <h1>Your account</h1>
      {status === 'loading' ? <p role="status" className="cc-account-muted">Loading…</p>
        : status === 'signed-out' ? <section className="cc-account-section">
          <p>Sign in to edit your profile and manage connected agents.</p>
          <button type="button" className="cc-button cc-button--primary" onClick={signIn}>Continue with Google</button>
          {error && <p className="cc-notice cc-notice--error" role="alert">{error}</p>}
        </section>
          : <><Profile profile={profile} /><Agents /><LinkedAccounts hash={hash} /></>}
    </main>
  </div>;
}
