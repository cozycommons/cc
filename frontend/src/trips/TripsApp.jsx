import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useMatch, useNavigate } from 'react-router-dom';
import { ArrowLeft, ArrowRight, Check, Compass, Luggage, Plus, RefreshCw, Search } from 'lucide-react';
import { useTripsAuth, localDemo } from './useTripsAuth.js';
import { tripRequest } from './api.js';
import { currencies, decimal, equalShares, money, shortDate, today, toMinor } from './money.js';
import { Button, Field, Form, Modal } from './ui.jsx';
import ImportTrip from './ImportTrip.jsx';
import { clearInvitation, readInvitation } from './invitation.js';
import '../../../design/cozy-wabi/components.css';
import './trips.css';

const categoryNames = { food: 'Food & drink', stay: 'Stay', transport: 'Getting around', activities: 'Things to do', other: 'Other' };
const categoryIcons = { food: '☕', stay: '⌂', transport: '↗', activities: '☀', other: '✳' };
const memberName = (member) => member?.display_name || member?.name || 'Unknown person';
const Avatar = ({ member, index = 0 }) => member?.avatar_url
  ? <img className="trips-avatar cc-avatar" src={member.avatar_url} alt="" loading="lazy" decoding="async" />
  : <span className={`trips-avatar cc-avatar trips-avatar--${index % 4}`} aria-hidden="true">{memberName(member).slice(0, 1).toUpperCase()}</span>;
const personName = (group, id) => memberName(group.members.find((member) => member.id === id));

function CreateTrip({ user, profile, onSave, onCancel }) {
  const [id] = useState(() => crypto.randomUUID());
  const [name, setName] = useState('');
  const displayName = profile?.display_name || user.user_metadata?.full_name || 'Me';
  const [currency, setCurrency] = useState('USD');
  return <Form onSubmit={() => onSave({ id, name: name.trim(), display_name: displayName.trim(), currency })} onCancel={onCancel} submit="Create trip">
    <Field label="Trip name"><input autoFocus required maxLength={80} placeholder="e.g. A weekend in the woods" value={name} onChange={(e) => setName(e.target.value)} /></Field>
    <Field label="Trip currency" hint="All expenses use this currency."><select value={currency} onChange={(e) => setCurrency(e.target.value)}>{currencies.map((code) => <option key={code}>{code}</option>)}</select></Field>
    <p className="trips-muted">Joining as {displayName} with your Commons account.</p>
    <p className="trips-muted">Start with a name. Add your people and the shared expenses as you go.</p>
  </Form>;
}

export function ExpenseForm({ group, user, expense, onSave, onCancel }) {
  const [id] = useState(() => expense?.id || crypto.randomUUID());
  const [description, setDescription] = useState(expense?.description || '');
  const [amount, setAmount] = useState(expense ? decimal(expense.amount_minor) : '');
  const [paidBy, setPaidBy] = useState(expense?.paid_by || group.members.find((m) => m.user_id === user.id)?.id || group.members[0].id);
  const [date, setDate] = useState(expense?.date || today());
  const [category, setCategory] = useState(expense?.category || 'other');
  const [notes, setNotes] = useState(expense?.notes || '');
  const [mode, setMode] = useState(expense?.split_mode || 'equal');
  const [participants, setParticipants] = useState(expense ? Object.keys(expense.shares) : group.members.map((m) => m.id));
  const [exact, setExact] = useState(Object.fromEntries(group.members.map((m) => [m.id, expense?.shares[m.id] === undefined ? '' : decimal(expense.shares[m.id])])));
  let parsedAmount = 0;
  try { parsedAmount = toMinor(amount); } catch { /* Incomplete input has no preview. */ }
  const selected = group.members.filter((m) => participants.includes(m.id));
  const equal = equalShares(parsedAmount, selected);
  let assigned = 0;
  try { assigned = selected.reduce((total, m) => total + toMinor(exact[m.id] || '0', true), 0); } catch { /* Validate at submit. */ }
  return <Form submit={expense ? 'Save changes' : 'Save expense'} onCancel={onCancel} onSubmit={() => {
    const amountMinor = toMinor(amount);
    if (!participants.length) throw new Error('Select at least one person to split with.');
    const shares = mode === 'exact' ? Object.fromEntries(selected.map((m) => [m.id, toMinor(exact[m.id] || '0', true)])) : {};
    if (mode === 'exact' && Object.values(shares).reduce((a, b) => a + b, 0) !== amountMinor) throw new Error('Exact shares must add up to the expense amount.');
    return onSave({ id, description: description.trim(), amount_minor: amountMinor, paid_by: paidBy, date, category, notes, split_mode: mode, participants, shares, revision: group.revision });
  }}>
    <Field label="Description"><input autoFocus required maxLength={80} placeholder="What was it for?" value={description} onChange={(e) => setDescription(e.target.value)} /></Field>
    <div className="trips-form-grid"><Field label={`Amount (${group.currency})`}><input inputMode="decimal" required placeholder="0.00" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
      <Field label="Paid by"><select value={paidBy} onChange={(e) => setPaidBy(e.target.value)}>{group.members.map((m) => <option value={m.id} key={m.id}>{memberName(m)}</option>)}</select></Field></div>
    <div className="trips-form-grid"><Field label="Date"><input type="date" required value={date} onChange={(e) => setDate(e.target.value)} /></Field>
      <Field label="Category"><select value={category} onChange={(e) => setCategory(e.target.value)}>{Object.entries(categoryNames).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></Field></div>
    <fieldset className="trips-split"><legend>Split between</legend>
      <div className="trips-segment" aria-label="Split method"><button type="button" aria-pressed={mode === 'equal'} onClick={() => setMode('equal')}>Equally</button><button type="button" aria-pressed={mode === 'exact'} onClick={() => setMode('exact')}>Exact amounts</button></div>
      {group.members.map((m, index) => <div className="trips-split-row" key={m.id}><label><input type="checkbox" checked={participants.includes(m.id)} onChange={(e) => setParticipants(e.target.checked ? [...participants, m.id] : participants.filter((id) => id !== m.id))} /><Avatar member={m} index={index} /><span>{memberName(m)}</span></label>
        {mode === 'equal' ? <span className="trips-mono">{money(equal[m.id] || 0, group.currency)}</span> : <input aria-label={`Share for ${memberName(m)} (${group.currency})`} inputMode="decimal" placeholder="0.00" disabled={!participants.includes(m.id)} value={exact[m.id]} onChange={(e) => setExact({ ...exact, [m.id]: e.target.value })} />}</div>)}
      <p className="trips-split-note">{mode === 'equal' ? 'Any extra pennies go in the order shown.' : `${money(parsedAmount - assigned, group.currency)} left to assign`}</p>
    </fieldset>
    <Field label="Note (optional)"><textarea rows={2} maxLength={1000} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="A little context for the group" /></Field>
  </Form>;
}

function RepaymentForm({ group, suggestion, onSave, onCancel }) {
  const [id] = useState(() => crypto.randomUUID());
  const [from, setFrom] = useState(suggestion?.from_member || group.members[0].id);
  const [to, setTo] = useState(suggestion?.to_member || group.members[1]?.id || group.members[0].id);
  const [amount, setAmount] = useState(suggestion ? decimal(suggestion.amount_minor) : '');
  const [date, setDate] = useState(today());
  const [notes, setNotes] = useState('');
  return <Form submit="Record repayment" onCancel={onCancel} onSubmit={() => {
    if (from === to) throw new Error('Choose two different people.');
    return onSave({ id, from_member: from, to_member: to, amount_minor: toMinor(amount), date, notes, revision: group.revision });
  }}>
    <p className="trips-muted">Log a payment that happened outside Cozy Trips.</p>
    <div className="trips-form-grid"><Field label="Who paid"><select value={from} onChange={(e) => setFrom(e.target.value)}>{group.members.map((m) => <option value={m.id} key={m.id}>{memberName(m)}</option>)}</select></Field>
      <Field label="Who received it"><select value={to} onChange={(e) => setTo(e.target.value)}>{group.members.map((m) => <option value={m.id} key={m.id}>{memberName(m)}</option>)}</select></Field></div>
    <div className="trips-form-grid"><Field label={`Amount (${group.currency})`}><input autoFocus inputMode="decimal" required placeholder="0.00" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
      <Field label="Payment date"><input required type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field></div>
    <Field label="Payment note (optional)"><input maxLength={1000} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="e.g. Venmo" /></Field>
  </Form>;
}

function MemberForm({ onSave, onCancel }) {
  const [name, setName] = useState('');
  return <Form submit="Add person" onCancel={onCancel} onSubmit={() => onSave(name.trim())}>
    <Field label="Person’s name"><input autoFocus required maxLength={80} placeholder="e.g. Alex" value={name} onChange={(e) => setName(e.target.value)} /></Field>
    <p className="trips-muted">You can include them in expenses straight away. Send their personal invite link when they’re ready to join.</p>
  </Form>;
}

function Invitation({ link, onClose }) {
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState('');
  return <><p className="trips-muted">This link claims one person’s place on the trip. It can be used once.</p><Field label="Personal invite link"><input readOnly value={link} onFocus={(e) => e.target.select()} /></Field>
    {error && <p role="alert">{error}</p>}<div className="trips-form-actions"><Button variant="ghost" onClick={onClose}>Done</Button><Button variant="primary" onClick={async () => { try { await navigator.clipboard.writeText(link); setCopied(true); } catch { setError('Select the link above and copy it.'); } }}>{copied ? <><Check size={16} /> Copied</> : 'Copy invite link'}</Button></div></>;
}

function TripView({ group, user, request, onUpdated, onRefresh }) {
  const [tab, setTab] = useState('Expenses');
  const [query, setQuery] = useState('');
  const [modal, setModal] = useState(null);
  const [status, setStatus] = useState('');
  const [refreshing, setRefreshing] = useState(false);
  const me = group.members.find((m) => m.user_id === user.id);
  const myBalance = group.balances[me?.id] || 0;
  const update = async (path, method, payload, message) => {
    const result = await request(`/groups/${group.id}${path}`, method, payload);
    onUpdated(result.group || result); setStatus(message); setModal(null);
    return result;
  };
  const invite = (result) => setModal({ type: 'invitation', link: `${window.location.origin}/trips/join/${group.id}#invite=${result.invite_token}` });
  const refresh = async () => { setRefreshing(true); try { await onRefresh(); setStatus('Trip is up to date.'); } catch (e) { setStatus(e.message); } finally { setRefreshing(false); } };
  const expenses = group.expenses.filter((e) => `${e.description} ${e.notes} ${personName(group, e.paid_by)} ${categoryNames[e.category]}`.toLowerCase().includes(query.toLowerCase())).sort((a, b) => b.date.localeCompare(a.date) || b.created_at.localeCompare(a.created_at));
  return <>
    <div className="trips-breadcrumb"><Link to="/trips"><ArrowLeft size={15} /> All trips</Link><button aria-label="Refresh trip" disabled={refreshing} onClick={refresh}><RefreshCw size={14} /> {refreshing ? 'Refreshing…' : 'Refresh'}</button></div>
    <section className="trips-heading"><div><p className="trips-eyebrow">A little adventure, shared</p><h1>{group.name}</h1><p className="trips-muted">{group.members.length} {group.members.length === 1 ? 'person' : 'people'} · {group.currency} · Created by {memberName(group.members.find((m) => m.user_id === group.owner_id))}</p></div><Button variant="primary" onClick={() => setModal({ type: 'expense' })}><Plus size={17} /> Add expense</Button></section>
    <div role="status" aria-live="polite" className="trips-status">{status}</div>
    <section className="trips-totals" aria-label="Trip summary"><div><span>Shared so far</span><strong>{money(group.total_minor, group.currency)}</strong><small>{group.expenses.length} {group.expenses.length === 1 ? 'expense' : 'expenses'}</small></div><div><span>{myBalance < 0 ? 'You owe' : myBalance > 0 ? 'You’re owed' : 'Your balance'}</span><strong className={myBalance > 0 ? 'trips-positive' : ''}>{money(Math.abs(myBalance), group.currency)}</strong><small>{myBalance === 0 ? 'All square for now' : 'Across the whole trip'}</small></div><div className="trips-people-total"><span>Your travel companions</span><div className="trips-avatar-stack">{group.members.map((m, i) => <Avatar key={m.id} member={m} index={i} />)}</div><button className="trips-text-button" onClick={() => setTab('People')}>View {group.members.length} people <ArrowRight size={13} /></button></div></section>
    <nav className="trips-tabs" aria-label="Trip sections">{['Expenses', 'Balances', 'People', 'Activity'].map((name) => <button key={name} aria-pressed={tab === name} onClick={() => setTab(name)}>{name}{name === 'Expenses' && <span>{group.expenses.length}</span>}</button>)}</nav>
    <div className="trips-columns"><section className="trips-ledger" aria-label={tab}>
      {tab === 'Expenses' && <><div className="trips-panel-heading"><h2>The shared tab</h2><label className="trips-search"><Search size={15} /><input aria-label="Search expenses" placeholder="Find an expense" value={query} onChange={(e) => setQuery(e.target.value)} /></label></div>
        {!expenses.length ? <div className="trips-empty"><span aria-hidden="true">✳</span><h3>{query ? 'No expenses match.' : 'A fresh page for this trip.'}</h3><p>{query ? 'Try another description or person’s name.' : 'From the first coffee to the last taxi, keep the shared costs here.'}</p>{!query && <Button onClick={() => setModal({ type: 'expense' })}><Plus size={15} /> Add your first expense</Button>}</div>
          : <ul className="trips-expense-list">{expenses.map((expense) => <li key={expense.id}><button className="trips-expense" aria-label={`Edit ${expense.description}`} onClick={() => setModal({ type: 'expense', expense })}><span className={`trips-category trips-category--${expense.category}`} aria-hidden="true">{categoryIcons[expense.category]}</span><span className="trips-expense-detail"><strong>{expense.description}</strong><small>{personName(group, expense.paid_by)} paid · {shortDate(expense.date)} · {Object.keys(expense.shares).length} {Object.keys(expense.shares).length === 1 ? 'person' : 'people'}</small></span><span className="trips-expense-amount"><strong>{money(expense.amount_minor, group.currency)}</strong><small>{expense.split_mode === 'equal' ? 'split equally' : 'exact split'}</small></span></button><button className="trips-text-button trips-remove" aria-label={`Delete ${expense.description}`} onClick={() => setModal({ type: 'delete_expense', item: expense })}>Delete</button></li>)}</ul>}</>}
      {tab === 'Balances' && <><div className="trips-panel-heading"><h2>Settle the shared tab</h2><Button onClick={() => setModal({ type: 'repayment' })} disabled={group.members.length < 2}>Record repayment</Button></div><p className="trips-muted">Suggested payments bring everyone’s trip balance back to zero.</p>
        {!group.transfers.length && <div className="trips-square"><Check size={22} /><h3>Everyone’s square.</h3><p>The shared tab is settled.</p></div>}
        {group.transfers.map((transfer) => <div className="trips-transfer" key={`${transfer.from_member}-${transfer.to_member}`}><p><strong>{personName(group, transfer.from_member)}</strong><ArrowRight size={16} /><strong>{personName(group, transfer.to_member)}</strong></p><strong>{money(transfer.amount_minor, group.currency)}</strong><Button onClick={() => setModal({ type: 'repayment', suggestion: transfer })}>Record payment</Button></div>)}
        <h3 className="trips-subheading">Recorded repayments</h3>{!group.repayments.length && <p className="trips-muted">No repayments recorded yet.</p>}
        {group.repayments.slice().reverse().map((p) => <div className="trips-repayment" key={p.id}><div><strong>{personName(group, p.from_member)} → {personName(group, p.to_member)}</strong><small>{shortDate(p.date)}{p.notes && ` · ${p.notes}`}</small></div><strong>{money(p.amount_minor, group.currency)}</strong><button className="trips-text-button" aria-label={`Remove repayment from ${personName(group, p.from_member)} to ${personName(group, p.to_member)}`} onClick={() => setModal({ type: 'delete_repayment', item: p })}>Remove</button></div>)}</>}
      {tab === 'People' && <><div className="trips-panel-heading"><h2>Good company</h2>{group.owner_id === user.id && <Button onClick={() => setModal({ type: 'member' })}><Plus size={16} /> Add person</Button>}</div><p className="trips-muted">Everyone on the trip can add and edit shared expenses.</p>{group.members.map((m, index) => <div className="trips-person" key={m.id}><Avatar member={m} index={index} /><div><strong>{memberName(m)}{m.user_id === user.id ? ' (you)' : ''}</strong><small>{m.user_id === group.owner_id ? 'Trip creator' : m.user_id ? 'Joined' : 'Not joined yet · can be included in expenses'}</small></div>{!m.user_id && group.owner_id === user.id && <Button onClick={() => setModal({ type: 'generate_invite', member: m })}>Invite</Button>}</div>)}</>}
      {tab === 'Activity' && <><div className="trips-panel-heading"><h2>Along the way</h2></div>{!group.activity.length && <p className="trips-muted">Your trip’s changes will appear here.</p>}<ol className="trips-activity">{group.activity.map((a) => <li key={a.id}><span aria-hidden="true">·</span><div><strong>{a.summary}</strong><small>{memberName(group.members.find((m) => m.user_id === a.user_id))} · {new Date(a.at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</small></div></li>)}</ol></>}
    </section><aside className="trips-balance-card"><p className="trips-eyebrow">Where everyone stands</p><h2>A fair share.</h2><p className="trips-muted">Positive means owed. Negative means owing.</p>{group.members.map((m, i) => <div className="trips-balance-row" key={m.id}><Avatar member={m} index={i} /><span>{memberName(m)}</span><strong className={group.balances[m.id] > 0 ? 'trips-positive' : ''}>{group.balances[m.id] > 0 ? '+' : ''}{money(group.balances[m.id], group.currency)}</strong></div>)}<div className="trips-balance-footer"><Compass size={18} /><p>Less keeping count.<br />More being there.</p></div></aside></div>
    {modal && <Modal title={{ expense: modal.expense ? 'Edit expense' : 'Add an expense', member: 'Bring your people', repayment: 'Record a repayment', invitation: 'A place on the trip', generate_invite: `Invite ${modal.member?.name}`, delete_expense: 'Delete this expense?', delete_repayment: 'Remove this repayment?' }[modal.type]} onClose={() => setModal(null)}>
      {modal.type === 'expense' && <ExpenseForm group={group} user={user} expense={modal.expense} onCancel={() => setModal(null)} onSave={(payload) => update(`/expenses${modal.expense ? `/${modal.expense.id}` : ''}`, modal.expense ? 'PUT' : 'POST', payload, 'Expense saved. Everyone’s balance is updated.')} />}
      {modal.type === 'member' && <MemberForm onCancel={() => setModal(null)} onSave={async (name) => invite(await update('/members', 'POST', { name, revision: group.revision }, `${name} added to the trip.`))} />}
      {modal.type === 'repayment' && <RepaymentForm group={group} suggestion={modal.suggestion} onCancel={() => setModal(null)} onSave={(payload) => update('/repayments', 'POST', payload, 'Repayment recorded.')} />}
      {modal.type === 'invitation' && <Invitation link={modal.link} onClose={() => setModal(null)} />}
      {modal.type === 'generate_invite' && <Form submit="Create invite link" onCancel={() => setModal(null)} onSubmit={async () => invite(await update(`/members/${modal.member.id}/invite`, 'POST', { revision: group.revision }, 'A new invitation is ready.'))}><p>Make a one-use link for {modal.member.name}. Any previous link for them will stop working.</p></Form>}
      {(modal.type === 'delete_expense' || modal.type === 'delete_repayment') && <Form destructive submit={modal.type === 'delete_expense' ? 'Delete expense' : 'Remove repayment'} onCancel={() => setModal(null)} onSubmit={() => update(`/${modal.type === 'delete_expense' ? 'expenses' : 'repayments'}/${modal.item.id}`, 'DELETE', { revision: group.revision }, 'Removed. Everyone’s balance is updated.')}><p>{modal.type === 'delete_expense' ? `${modal.item.description} · ${money(modal.item.amount_minor, group.currency)}` : money(modal.item.amount_minor, group.currency)}</p><p className="trips-muted">This will recalculate everyone’s balance.</p></Form>}
    </Modal>}
  </>;
}

function Workspace({ auth, tripId, joinId, invitation }) {
  const navigate = useNavigate();
  const [groups, setGroups] = useState([]);
  const [group, setGroup] = useState(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState('');
  const [creating, setCreating] = useState(false);
  const [importing, setImporting] = useState(false);
  const request = useCallback((path, method, payload) => tripRequest(auth.supabase, path, method, payload), [auth.supabase]);
  const load = async () => {
    if (tripId) setGroup(await request(`/groups/${tripId}`));
    else setGroups(await request('/groups'));
  };
  useEffect(() => {
    let active = true;
    setLoading(true); setError(''); setGroup(null);
    const path = tripId ? `/groups/${tripId}` : '/groups';
    request(path).then((result) => { if (active) { if (tripId) setGroup(result); else setGroups(result); } }).catch((e) => { if (active) setError(e.message); }).finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
  }, [tripId, auth.user.id, request]); // A new identity remounts this workspace.
  if (joinId) return <section className="trips-join cc-card"><p className="trips-eyebrow">A place saved for you</p><h1>You’re invited.</h1><p>Join this trip to see the shared tab and add your expenses.</p><Form submit="Join trip" onCancel={() => navigate('/trips')} onSubmit={async () => {
    if (!invitation) throw new Error('The invitation link is missing its secret. Open the original link again.');
    const result = await request(`/groups/${joinId}/join`, 'POST', { invite_token: invitation });
    clearInvitation(joinId); navigate(`/trips/${result.id}`);
  }}><p className="trips-muted">Joining as {auth.profile?.display_name || auth.user.user_metadata?.full_name || auth.user.email}.</p></Form></section>;
  if (loading) return <p className="trips-loading" role="status">Opening the shared tab…</p>;
  if (error) return <div className="trips-empty"><p role="alert">{error}</p><Button onClick={async () => { setError(''); setLoading(true); try { await load(); } catch (e) { setError(e.message); } finally { setLoading(false); } }}>Try again</Button><Link to="/trips">All trips</Link></div>;
  if (tripId && group) return <TripView key={group.id} group={group} user={auth.user} request={request} onUpdated={setGroup} onRefresh={load} />;
  return <><section className="trips-heading trips-heading--home"><div><p className="trips-eyebrow">Cozy Commons / Trips</p><h1>Your trips</h1><p className="trips-intro">Shared expenses, people, and balances.</p></div><div className="trips-home-actions"><Button onClick={() => setImporting(true)}>Import from Splitwise</Button><Button variant="primary" onClick={() => setCreating(true)}><Plus size={17} /> New trip</Button></div></section>
    {!groups.length ? <div className="trips-empty trips-empty--home"><Luggage size={35} strokeWidth={1.2} /><h2>Where are we going?</h2><p>Start a trip, bring your people,<br />and keep the shared expenses in one place.</p><Button onClick={() => setCreating(true)}><Plus size={16} /> Create your first trip</Button></div>
      : <div className="trips-trip-grid">{groups.map((g) => { const myId = g.members.find((m) => m.user_id === auth.user.id)?.id; const balance = g.balances[myId] || 0; return <Link className="cc-card trips-trip-card" to={`/trips/${g.id}`} key={g.id}><span className="trips-eyebrow">{g.currency} · {g.members.length} people</span><h2>{g.name}</h2><p>{money(g.total_minor, g.currency)} shared · {g.expenses.length} expenses</p><div><span className={balance >= 0 ? 'trips-positive' : ''}>{balance === 0 ? 'You’re all square' : `${balance > 0 ? 'You’re owed' : 'You owe'} ${money(Math.abs(balance), g.currency)}`}</span><ArrowRight size={18} /></div></Link>; })}</div>}
    {creating && <Modal title="Start a new trip" onClose={() => setCreating(false)}><CreateTrip user={auth.user} profile={auth.profile} onCancel={() => setCreating(false)} onSave={async (payload) => { const result = await request('/groups', 'POST', payload); setCreating(false); navigate(`/trips/${result.id}`); }} /></Modal>}
    {importing && <Modal title="Import from Splitwise" onClose={() => setImporting(false)}><ImportTrip request={request} onCancel={() => setImporting(false)} onImported={group => { setImporting(false); navigate(`/trips/${group.id}`); }} /></Modal>}
  </>;
}

export default function TripsApp() {
  const auth = useTripsAuth();
  const tripId = useMatch('/trips/:tripId')?.params.tripId;
  const joinId = useMatch('/trips/join/:tripId')?.params.tripId;
  const [error, setError] = useState('');
  const [signingIn, setSigningIn] = useState(false);
  const invitation = useRef('');
  useEffect(() => { window.scrollTo(0, 0); }, [tripId, joinId, auth.user?.id]);
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
  return <div className="cc-page trips"><a href="#trips-main" className="trips-skip">Skip to trip</a><header className="cc-navbar trips-navbar"><Link className="cc-brand" to="/" aria-label="Cozy Commons home"><span className="cc-brand__cozy">cozy</span><span className="cc-brand__commons">commons</span></Link><Link to="/trips" className="trips-wordmark"><span aria-hidden="true">↗</span> Cozy Trips</Link><div className="trips-account">{auth.user && <><span className="trips-account-identity"><Avatar member={auth.profile || { name: auth.user.user_metadata?.full_name || "Me" }} /><span>{auth.profile?.display_name || auth.user.user_metadata?.full_name || auth.user.email}</span></span><Button variant="ghost" onClick={async () => { try { await auth.signOut(); } catch (e) { setError(e.message); } }}>Sign out</Button></>}{localDemo && <span className="trips-demo-badge">LOCAL DEMO</span>}</div></header>
    {(error || auth.error) && <p className="trips-error" role="alert">{error || auth.error}</p>}
    <main id="trips-main">{auth.loading ? <p className="trips-loading" role="status">Opening Cozy Trips…</p> : auth.user ? <Workspace key={auth.user.id} auth={auth} tripId={tripId} joinId={joinId} invitation={invitation.current} /> : <section className="trips-welcome"><div><p className="trips-eyebrow">A Cozy Commons project</p><h1>Good trips.<br /><em>Clear tabs.</em></h1><p className="trips-intro">For the cabin, the coffees,<br />and everything you share along the way.</p>{joinId && <p>You have a personal invitation waiting. Sign in to join.</p>}{!localDemo && <><Button variant="primary" disabled={signingIn} onClick={() => signIn()}>Continue with Google <ArrowRight size={17} /></Button><p className="trips-muted">Your Cozy Commons account comes along.</p></>}
      {localDemo && <div className="trips-demo"><p className="trips-eyebrow">Try it locally · synthetic accounts</p><div>{['Matt', 'Alex', 'Jamie'].map((name) => <Button variant={name === 'Matt' ? 'primary' : 'secondary'} key={name} disabled={signingIn} onClick={() => signIn(name)}>Continue as {name}</Button>)}</div></div>}</div><div className="trips-welcome-note" aria-hidden="true"><span className="trips-note-mark">↗</span><p>More memories.<br /><em>Less mental math.</em></p><hr /><span>SHARED COSTS, GOOD COMPANY.</span><Luggage size={60} strokeWidth={1} /></div></section>}</main>
    <footer className="trips-footer"><span>Cozy Trips</span><span>A little less to keep track of.</span><Link to="/">Back to the commons <ArrowRight size={12} /></Link></footer>
  </div>;
}
