import React, { useEffect, useRef, useState } from 'react';
import { adminRequest } from './api.js';
import { Skeleton } from '../design/system/DataPatterns.jsx';

export default function Users({ onAccessLost, onRoleChanged }) {
  const [search, setSearch] = useState('');
  const [filter, setFilter] = useState('');
  const [offset, setOffset] = useState(0);
  const [refresh, setRefresh] = useState(0);
  const [data, setData] = useState(null);
  const [history, setHistory] = useState([]);
  const [error, setError] = useState('');
  const [pending, setPending] = useState(null);
  const [busy, setBusy] = useState(false);
  const confirmation = useRef(null);
  const trigger = useRef(null);
  useEffect(() => {
    if (pending) confirmation.current?.focus();
    else trigger.current?.focus();
  }, [pending]);
  useEffect(() => {
    const controller = new AbortController();
    let current = true;
    setData(null); setError(''); setPending(null);
    Promise.all([
      adminRequest(`/users?search=${encodeURIComponent(filter)}&offset=${offset}`, { signal: controller.signal }),
      adminRequest('/role-history', { signal: controller.signal }),
    ]).then(([accounts, audit]) => {
      if (current) { setData(accounts); setHistory(audit); }
    }).catch((err) => {
      if (!current || err.name === 'AbortError') return;
      if (err.status === 401 || err.status === 403) onAccessLost(err.status);
      else setError(err.message);
    });
    return () => { current = false; controller.abort(); };
  }, [filter, offset, refresh, onAccessLost]);
  const changeRole = async () => {
    setBusy(true); setError('');
    try {
      await adminRequest(`/users/${pending.user_id}/role`, {
        method: 'PUT', body: { role: pending.role === 'admin' ? 'member' : 'admin', expected_role: pending.role },
      });
      setPending(null); setRefresh((n) => n + 1); onRoleChanged();
    } catch (err) {
      if (err.status === 401 || err.status === 403) onAccessLost(err.status);
      else setError(err.message);
    } finally { setBusy(false); }
  };
  return <section className="cc-data-panel admin-card admin-users" aria-busy={busy}>
    <header><h2>Users</h2><button className="cc-button cc-button--secondary" disabled={busy} onClick={() => setRefresh((n) => n + 1)}>Refresh users</button></header>
    <form className="admin-controls" onSubmit={(event) => { event.preventDefault(); setOffset(0); setFilter(search.trim()); setRefresh((n) => n + 1); }}>
      <label>Search users<input className="cc-input" type="search" maxLength={200} placeholder="Name or email" value={search} disabled={busy} onChange={(event) => setSearch(event.target.value)} /></label>
      <button className="cc-button cc-button--secondary" disabled={busy}>Search</button>
    </form>
    {error && <p className="cc-notice cc-notice--error" role="alert">{error}</p>}
    {pending && <section className="admin-role-confirm" role="region" aria-label="Confirm role change" onKeyDown={(event) => { if (event.key === 'Escape' && !busy) setPending(null); }}>
      <p>Make <strong>{pending.email}</strong> {pending.role === 'admin' ? 'a member' : 'an admin'}?</p>
      <div className="admin-controls"><button ref={confirmation} className="cc-button cc-button--primary" disabled={busy} onClick={changeRole}>{busy ? 'Saving…' : 'Confirm role change'}</button><button className="cc-button cc-button--secondary" disabled={busy} onClick={() => setPending(null)}>Cancel</button></div>
    </section>}
    {!data ? !error && <Skeleton label="Loading users" /> : <>
      {!data.users.length ? <p>No users found</p> : <div className="admin-table"><table><thead><tr><th scope="col">Account</th><th scope="col">Role</th><th scope="col">Action</th></tr></thead><tbody>{data.users.map((user) => <tr key={user.user_id}>
        <td><strong>{user.display_name || user.email}</strong><span className="admin-user-email">{user.email}</span>{!user.verified && <span>Unverified</span>}</td><td>{user.role === 'admin' ? 'Admin' : 'Member'}</td>
        <td><button className="cc-button cc-button--secondary" disabled={busy || Boolean(pending) || (!user.verified && user.role !== 'admin')} aria-label={`Make ${user.email} ${user.role === 'admin' ? 'a member' : 'an admin'}`} onClick={(event) => { trigger.current = event.currentTarget; setPending(user); }}>{user.role === 'admin' ? 'Make member' : 'Make admin'}</button></td>
      </tr>)}</tbody></table></div>}
      <div className="admin-controls"><button className="cc-button cc-button--secondary" disabled={busy || Boolean(pending) || offset === 0} onClick={() => setOffset((n) => Math.max(0, n - 50))}>Previous</button><span>Page {offset / 50 + 1}</span><button className="cc-button cc-button--secondary" disabled={busy || Boolean(pending) || !data.has_more} onClick={() => setOffset((n) => n + 50)}>Next</button></div>
      <details><summary>Recent role changes</summary>{!history.length ? <p>No role changes</p> : <ul className="admin-role-history">{history.map((entry) => <li key={entry.id}><strong>{entry.user_label || entry.user_id}</strong>: {entry.old_role} → {entry.new_role}<br /><span>{entry.actor_label || (entry.source === 'migration' ? 'Initial migration' : 'Trusted recovery')} · {new Date(entry.created_at).toLocaleString()}</span></li>)}</ul>}</details>
    </>}
  </section>;
}
