import React, { useEffect, useRef, useState } from 'react';
import { Link } from 'react-router-dom';
import PlayerAvatar from '../dice/components/PlayerAvatar.jsx';
import { signInToCommons, signOutOfCommons, useCommonsIdentity } from './commonsIdentity.js';

// The signed-in person, on every page: their avatar opens a menu with the
// account page, agent connections, the product's own links and sign out.
//
// `items` are product links, `{ label, to }` or `{ label, onSelect }`.
// `onSignIn` replaces Google sign-in (a local harness); `null` hides the button
// for products whose own page owns sign-in.
export default function AccountMenu({ items = [], onSignIn }) {
  const { status, profile } = useCommonsIdentity();
  const [open, setOpen] = useState(false);
  const [error, setError] = useState('');
  const root = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const outside = (event) => { if (!root.current?.contains(event.target)) setOpen(false); };
    const escape = (event) => { if (event.key === 'Escape') setOpen(false); };
    document.addEventListener('pointerdown', outside);
    document.addEventListener('keydown', escape);
    return () => { document.removeEventListener('pointerdown', outside); document.removeEventListener('keydown', escape); };
  }, [open]);
  useEffect(() => { if (status !== 'signed-in') setOpen(false); }, [status]);

  if (status === 'loading') return <span className="cc-account-placeholder" aria-hidden="true" />;
  if (status === 'signed-out') {
    if (onSignIn === null) return null;
    const signIn = async () => {
      setError('');
      try { await (onSignIn || signInToCommons)(); } catch (err) { setError(err?.message || 'Could not start sign-in.'); }
    };
    return <span className="cc-account">
      <button type="button" className="cc-account-signin" onClick={signIn}>Sign in</button>
      {error && <span role="alert" className="cc-account-error">{error}</span>}
    </span>;
  }

  const close = () => setOpen(false);
  const signOut = async () => {
    close();
    try { await signOutOfCommons(); } catch (err) { setError(err?.message || 'Could not sign out.'); }
  };
  return (
    <div className="cc-account" ref={root}>
      <button type="button" className="cc-account-trigger" aria-haspopup="true" aria-expanded={open}
        aria-label={`Account: ${profile.display_name}`} title={profile.display_name} onClick={() => setOpen((value) => !value)}>
        <PlayerAvatar profile={profile} size={32} linkToProfile={false} />
      </button>
      {error && <span role="alert" className="cc-account-error">{error}</span>}
      {open && (
        <nav className="cc-account-menu" aria-label="Account">
          <div className="cc-account-who">
            <PlayerAvatar profile={profile} size={40} linkToProfile={false} />
            <div><strong>{profile.display_name}</strong>{profile.email && <span>{profile.email}</span>}</div>
          </div>
          <Link to="/account" onClick={close}>Your profile</Link>
          <Link to="/account#agents" onClick={close}>Connected agents</Link>
          {items.length > 0 && <hr />}
          {items.map((item) => (item.to
            ? <Link key={item.label} to={item.to} onClick={close}>{item.label}</Link>
            : <button key={item.label} type="button" onClick={() => { close(); item.onSelect(); }}>{item.label}</button>))}
          <hr />
          <button type="button" onClick={signOut}>Sign out</button>
        </nav>
      )}
    </div>
  );
}
