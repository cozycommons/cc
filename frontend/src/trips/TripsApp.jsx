import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useLocation, useMatch, useNavigate } from 'react-router-dom';
import { ArrowRight, Download, LogOut, Plus } from 'lucide-react';
import { Suitcase, TripStamp, tripSticker } from './doodles.jsx';
import { useTripsAuth, localDemo } from './useTripsAuth.js';
import { tripRequest } from './api.js';
import { currencies, money } from './money.js';
import { AvatarStack, Button, Field, Form, Modal } from './ui.jsx';
import ImportTrip from './ImportTrip.jsx';
import TripView from './TripView.jsx';
import VenmoConfirmation from './VenmoConfirmation.jsx';
import { clearInvitation, readInvitation } from './invitation.js';
import PlayerAvatar from '../dice/components/PlayerAvatar.jsx';
import SiteHeader from '../components/SiteHeader.jsx';
import '../../../design/cozy-wabi/components.css';
import './trips.css';

export { ExpenseForm } from './ExpenseForm.jsx';

function CreateTrip({ displayName, onSave, onCancel }) {
  const [id] = useState(() => crypto.randomUUID());
  const [name, setName] = useState('');
  const [currency, setCurrency] = useState('USD');
  return <Form name="create_trip" onSubmit={() => onSave({ id, name: name.trim(), display_name: displayName.trim(), currency })} onCancel={onCancel} submit="Create trip">
    <Field label="Trip name"><input name="name" autoFocus required maxLength={80} autoComplete="off" placeholder="Tahoe weekend" value={name} onChange={(e) => setName(e.target.value)} /></Field>
    <Field label="Currency"><select name="currency" value={currency} onChange={(e) => setCurrency(e.target.value)}>{currencies.map((code) => <option key={code}>{code}</option>)}</select></Field>
    <p className="trips-muted">You’ll join as {displayName}.</p>
  </Form>;
}

function ProfileDialog({ auth, profile, onClose, onSignOut }) {
  return <Modal title="Your profile" onClose={onClose}>
    <div className="trips-profile"><PlayerAvatar profile={profile} size={56} linkToProfile={false} /><div><strong>{profile.display_name}</strong></div></div>
    {auth.profile
      ? <VenmoConfirmation username={auth.profile.venmo_username} confirmed={auth.profile.venmo_confirmed} request={(...args) => tripRequest(auth.supabase, ...args)} onCancel={onClose}
        onConfirm={async (username) => { await auth.saveVenmo(username, true); onClose(); }} />
      : <p className="trips-muted">Your profile is still loading.</p>}
    <div className="trips-profile-signout"><Button variant="ghost" onClick={onSignOut}><LogOut size={14} aria-hidden="true" />Sign out</Button></div>
  </Modal>;
}

// One line for every trip together, per currency, like Splitwise's overall balance.
function overall(groups, userId) {
  const totals = {};
  for (const g of groups) {
    const mine = g.balances[g.members.find((m) => m.user_id === userId)?.id] || 0;
    if (mine) totals[g.currency] = (totals[g.currency] || 0) + mine;
  }
  const parts = Object.entries(totals).filter(([, amount]) => amount)
    .map(([currency, amount]) => ({ amount, text: `${amount > 0 ? 'You’re owed' : 'You owe'} ${money(Math.abs(amount), currency)}` }));
  if (!groups.length) return null;
  return parts.length ? parts : [{ amount: 0, text: 'All square across your trips' }];
}

function JoinTrip({ joinId, invitation, request, displayName, onJoined, onCancel, onOpen }) {
  const [preview, setPreview] = useState(null);
  const [error, setError] = useState(invitation ? '' : 'This invite link is missing its code. Open the original link again.');
  useEffect(() => {
    if (!invitation) return undefined;
    let current = true;
    request(`/groups/${joinId}/invite-preview`, 'POST', { invite_token: invitation })
      .then((result) => current && setPreview(result), (e) => current && setError(e.message));
    return () => { current = false; };
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  if (error) return <section className="trips-join"><h1>Join trip</h1><p className="trips-error" role="alert">{error}</p><Link to="/trips">All trips</Link></section>;
  if (!preview) return <p className="trips-loading" role="status">Opening your invite…</p>;
  if (preview.already_member) return <section className="trips-join"><h1>{preview.trip_name}</h1>
    <p className="trips-muted">You’re already on this trip.</p><Button variant="primary" onClick={onOpen}>Open trip <ArrowRight size={16} aria-hidden="true" /></Button></section>;
  const balance = preview.balance_minor;
  return <section className="trips-join"><p className="trips-greeting">{preview.inviter ? `${preview.inviter} invited you` : 'You’re invited'}</p><h1>{preview.trip_name}</h1>
    <div className="trips-join-card">
      <p>You’ll take <strong>{preview.member_name}</strong>’s place on this trip of {preview.member_count} people.</p>
      <p>{balance === 0 ? `${preview.member_name} is all square so far.` : `${preview.member_name} ${balance < 0 ? 'owes' : 'is owed'} ${money(Math.abs(balance), preview.currency)} so far.`}</p>
    </div>
    <Form name="join" submit={`Join as ${preview.member_name}`} onCancel={onCancel} onSubmit={onJoined}>
      <p className="trips-muted">Signed in as {displayName}. Not {preview.member_name}? Ask {preview.inviter || 'the trip creator'} for your own link. Each link is for one person.</p>
    </Form></section>;
}

function TripList({ groups, userId }) {
  if (!groups.length) return <div className="trips-empty"><Suitcase size={64} className="trips-empty-doodle" /><p>No trips yet. Pack one, or bring yours over from Splitwise.</p></div>;
  return <ul className="trips-trip-list">{groups.map((g) => {
    const myId = g.members.find((m) => m.user_id === userId)?.id;
    const balance = g.balances[myId] || 0;
    return <li key={g.id}><Link className="trips-trip-row" style={{ '--cover': tripSticker(g).cover }} to={`/trips/${g.id}`}>
      <TripStamp trip={g} />
      <span className="trips-trip-row-main"><strong>{g.name}</strong><small><AvatarStack members={g.members} max={4} />{g.members.length} people · {g.expenses.length} {g.expenses.length === 1 ? 'expense' : 'expenses'}</small></span>
      <span className="trips-trip-row-balance"><strong className={balance > 0 ? 'trips-positive' : balance < 0 ? 'trips-owe' : ''}>{balance === 0 ? 'All square' : `${balance > 0 ? 'You’re owed' : 'You owe'} ${money(Math.abs(balance), g.currency)}`}</strong><small>{money(g.total_minor, g.currency)} total</small></span>
      <ArrowRight size={16} aria-hidden="true" />
    </Link></li>;
  })}</ul>;
}

function Workspace({ auth, tripId, joinId, invitation, onEditProfile }) {
  const navigate = useNavigate();
  // Shown once after deleting a trip; cleared from history so a reload doesn't repeat it.
  const location = useLocation();
  const [deletedNotice] = useState(() => location.state?.notice);
  useEffect(() => { if (deletedNotice) navigate(location.pathname, { replace: true, state: null }); }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const [groups, setGroups] = useState([]);
  const [group, setGroup] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const request = useCallback((path, method, payload) => tripRequest(auth.supabase, path, method, payload), [auth.supabase]);
  // A workspace belongs to one account and one route (it is keyed on both), so late results for another never land here.
  // Within a trip, revisions only grow: a slow refresh must not replace a newer saved version.
  const accept = (result) => {
    if (!alive.current) return result;
    if (!tripId) setGroups(result);
    else if (result?.id === tripId && Array.isArray(result.members)) setGroup((current) => (current && current.revision > result.revision ? current : result));
    return result;
  };
  const load = async () => accept(await request(tripId ? `/groups/${tripId}` : '/groups'));
  const go = (path) => { if (alive.current) navigate(path); };
  useEffect(() => {
    setLoading(true); setError('');
    load().catch((e) => alive.current && setError(e.message)).finally(() => alive.current && setLoading(false));
  }, []); // eslint-disable-line react-hooks/exhaustive-deps
  const venmo = `${auth.profile?.venmo_username || ''}:${Boolean(auth.profile?.venmo_confirmed)}`;
  const firstVenmo = useRef(venmo);
  useEffect(() => { if (venmo !== firstVenmo.current) { firstVenmo.current = venmo; load().catch(() => {}); } }, [venmo]); // eslint-disable-line react-hooks/exhaustive-deps
  const displayName = auth.profile?.display_name || auth.user.user_metadata?.full_name || auth.user.email || 'Me';

  if (joinId) return <JoinTrip joinId={joinId} invitation={invitation} request={request} displayName={displayName}
    onCancel={() => navigate('/trips')} onOpen={() => { clearInvitation(joinId); go(`/trips/${joinId}`); }}
    onJoined={async () => {
      const result = await request(`/groups/${joinId}/join`, 'POST', { invite_token: invitation });
      clearInvitation(joinId); go(`/trips/${result.id}?tab=balances`);
    }} />;
  if (loading) return <p className="trips-loading" role="status">Loading…</p>;
  if (error) return <div className="trips-empty"><p role="alert">{error}</p><Button onClick={async () => { setError(''); setLoading(true); try { await load(); } catch (e) { setError(e.message); } finally { setLoading(false); } }}>Try again</Button> <Link to="/trips">All trips</Link></div>;
  if (tripId && group) {
    const linked = group.members.some((member) => member.user_id === auth.user.id);
    if (linked && !auth.profile) return auth.error
      ? <div className="trips-empty"><Button onClick={() => window.location.reload()}>Reload profile</Button></div>
      : <p className="trips-loading" role="status">Loading your profile…</p>;
    if (linked && auth.profile?.venmo_confirmed === false) return <VenmoConfirmation key={auth.user.id}
      request={request} username={auth.profile.venmo_username} onConfirm={username => auth.saveVenmo(username, true)} onCancel={() => navigate('/trips')} />;
    return <TripView key={group.id} group={group} user={auth.user} profile={auth.profile} request={request} onUpdated={accept} onRefresh={load} onEditProfile={onEditProfile} />;
  }
  return <>
    {deletedNotice && <p role="status" className="trips-notice">{deletedNotice}</p>}
    <section className="trips-heading trips-heading--home"><div><p className="trips-greeting">Hi {displayName.split(/\s+/)[0]}, where to next?</p><h1 tabIndex={-1}>Your trips</h1>
      {overall(groups, auth.user.id)?.map(({ amount, text }) => <p key={text} className={`trips-overall ${amount > 0 ? 'trips-positive' : amount < 0 ? 'trips-owe' : ''}`}>{text}</p>)}</div><div className="trips-home-actions">
      <Button onClick={() => setImporting(true)}><Download size={15} aria-hidden="true" />Import from Splitwise</Button>
      <Button variant="primary" onClick={() => setCreating(true)}><Plus size={17} aria-hidden="true" />New trip</Button></div></section>
    <TripList groups={groups} userId={auth.user.id} />
    {creating && <Modal title="New trip" onClose={() => setCreating(false)}><CreateTrip displayName={displayName} onCancel={() => setCreating(false)} onSave={async (payload) => { const result = await request('/groups', 'POST', payload); if (alive.current) setCreating(false); go(`/trips/${result.id}?tab=people`); }} /></Modal>}
    {importing && <Modal title="Import from Splitwise" onClose={() => setImporting(false)}><ImportTrip request={request} onCancel={() => setImporting(false)} onImported={(imported) => { if (alive.current) setImporting(false); go(`/trips/${imported.id}`); }} /></Modal>}
  </>;
}

export default function TripsApp() {
  const auth = useTripsAuth();
  const tripId = useMatch('/trips/:tripId')?.params.tripId;
  const joinId = useMatch('/trips/join/:tripId')?.params.tripId;
  // Join and trip routes for the same id must not share a workspace, or the joined trip never loads.
  const workspaceKey = `${auth.user?.id}:${joinId ? `join:${joinId}` : tripId || 'home'}`;
  const headerProfile = auth.profile || { user_id: auth.user?.id,
    display_name: auth.user?.user_metadata?.full_name || auth.user?.user_metadata?.name || auth.user?.email || 'Me',
    avatar_url: auth.user?.user_metadata?.avatar_url || auth.user?.user_metadata?.picture };
  const [error, setError] = useState('');
  const [signingIn, setSigningIn] = useState(false);
  const [profileOpen, setProfileOpen] = useState(false);
  const invitation = useRef('');
  useEffect(() => { window.scrollTo(0, 0); }, [tripId, joinId, auth.user?.id]);
  useEffect(() => { setProfileOpen(false); }, [auth.user?.id]);
  useEffect(() => {
    document.body.classList.add('trips-body');
    const title = document.title; document.title = 'Cozy Trips · Cozy Commons';
    return () => { document.body.classList.remove('trips-body'); document.title = title; };
  }, []);
  // Save fragment secrets before Google OAuth uses the URL fragment for its callback.
  if (joinId) {
    invitation.current = readInvitation(joinId);
  }
  const signIn = async (name) => { setError(''); setSigningIn(true); try { if (name) await auth.signInLocal(name); else await auth.signIn(); } catch (e) { setError(e.message); } finally { setSigningIn(false); } };
  const signOut = async () => { try { setProfileOpen(false); await auth.signOut(); } catch (e) { setError(e.message); } };
  return <div className="cc-page trips"><a href="#trips-main" className="trips-skip">Skip to trip</a>
    <SiteHeader product="Cozy Trips" to="/trips" icon={<Suitcase size={26} />}>
      {localDemo && <span className="trips-demo-badge">LOCAL</span>}
      {auth.user && <>
        <button className="trips-account-identity" aria-label={`Signed in as ${headerProfile.display_name}. Open profile`} onClick={() => setProfileOpen(true)}>
          <PlayerAvatar profile={headerProfile} size={32} linkToProfile={false} /><span className="trips-account-name">{headerProfile.display_name}</span></button>
        <Button variant="ghost" className="trips-signout" aria-label="Sign out" onClick={signOut}><LogOut size={14} aria-hidden="true" /><span>Sign out</span></Button>
      </>}
    </SiteHeader>
    {(error || auth.error) && <p className="trips-error" role="alert">{error || auth.error}</p>}
    <main id="trips-main">{auth.loading ? <p className="trips-loading" role="status">Loading…</p> : auth.user
      ? <Workspace key={workspaceKey} auth={auth} tripId={tripId} joinId={joinId} invitation={invitation.current} onEditProfile={() => setProfileOpen(true)} />
      : <section className="trips-welcome"><span className="trips-welcome-mark" aria-hidden="true"><Suitcase size={40} /></span><h1>Cozy Trips</h1><p className="trips-intro">Split trip costs with friends, then square up.</p>{joinId && <p>Sign in to accept your invite.</p>}
        {!localDemo && <Button variant="primary" disabled={signingIn} onClick={() => signIn()}>Continue with Google <ArrowRight size={17} aria-hidden="true" /></Button>}
        {localDemo && <div className="trips-demo"><p className="trips-eyebrow">Local test accounts</p><div>{['Matt', 'Alex', 'Jamie'].map((name) => <Button variant={name === 'Matt' ? 'primary' : 'secondary'} key={name} disabled={signingIn} onClick={() => signIn(name)}>Continue as {name}</Button>)}</div></div>}</section>}</main>
    {profileOpen && auth.user && <ProfileDialog auth={auth} profile={headerProfile} onClose={() => setProfileOpen(false)} onSignOut={signOut} />}
  </div>;
}
