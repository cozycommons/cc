import React, { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useMatch, useNavigate } from 'react-router-dom';
import { ArrowLeft, ArrowRight, Banknote, BedDouble, Car, Check, Download, History, Link2, LogOut, Luggage, Plus, ReceiptText, RefreshCw, Search, Ticket, Trash2, UserPlus, UsersRound, Utensils, Wallet } from 'lucide-react';
import { useTripsAuth, localDemo } from './useTripsAuth.js';
import { tripRequest } from './api.js';
import { currencies, decimal, equalShares, money, shortDate, today, toMinor } from './money.js';
import { Button, Field, Form, Modal } from './ui.jsx';
import ImportTrip from './ImportTrip.jsx';
import { clearInvitation, readInvitation } from './invitation.js';
import { balanceBreakdown } from './balances.js';
import PlayerAvatar from '../dice/components/PlayerAvatar.jsx';
import '../../../design/cozy-wabi/components.css';
import './trips.css';

const categoryNames = { food: 'Food & drink', stay: 'Accommodation', transport: 'Transport', activities: 'Activities', other: 'Other' };
const sectionIcons = { Expenses: ReceiptText, Balances: Wallet, People: UsersRound, Activity: History };
const SectionHeading = ({ icon: Icon, children }) => <h2 className="trips-section-heading"><Icon size={16} aria-hidden="true" />{children}</h2>;
const memberName = (member) => member?.display_name || member?.name || 'Unknown person';
const Avatar = ({ member, index = 0 }) => member?.avatar_url
  ? <img className="trips-avatar cc-avatar" src={member.avatar_url} alt="" loading="lazy" decoding="async" />
  : <span className={`trips-avatar cc-avatar trips-avatar--${index % 4}`} aria-hidden="true">{memberName(member).slice(0, 1).toUpperCase()}</span>;
const personName = (group, id) => memberName(group.members.find((member) => member.id === id));
const expenseContext = (group, expense) => `${expense.description}, ${money(expense.amount_minor, group.currency)} paid by ${personName(group, expense.paid_by)} on ${expense.date}`;
function ExpenseCategory({ category }) {
  const Icon = { food: Utensils, stay: BedDouble, transport: Car, activities: Ticket }[category] || ReceiptText;
  return <Icon size={16} className="trips-expense-category" aria-hidden="true" />;
}

function CreateTrip({ user, profile, onSave, onCancel }) {
  const [id] = useState(() => crypto.randomUUID());
  const [name, setName] = useState('');
  const displayName = profile?.display_name || user.user_metadata?.full_name || 'Me';
  const [currency, setCurrency] = useState('USD');
  return <Form onSubmit={() => onSave({ id, name: name.trim(), display_name: displayName.trim(), currency })} onCancel={onCancel} submit="Create trip">
    <Field label="Trip name"><input autoFocus required maxLength={80} placeholder="e.g. A weekend in the woods" value={name} onChange={(e) => setName(e.target.value)} /></Field>
    <Field label="Trip currency" hint="All expenses use this currency."><select value={currency} onChange={(e) => setCurrency(e.target.value)}>{currencies.map((code) => <option key={code}>{code}</option>)}</select></Field>
    <p className="trips-muted">Joining as {displayName} with your Commons account.</p>
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
    <Field label="Note (optional)"><textarea rows={2} maxLength={1000} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Optional details" /></Field>
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
  const breakdown = me ? balanceBreakdown(group, me.id) : null;
  const update = async (path, method, payload, message) => {
    const result = await request(`/groups/${group.id}${path}`, method, payload);
    onUpdated(result.group || result); setStatus(message); setModal(null);
    return result;
  };
  const invite = (result) => setModal({ type: 'invitation', link: `${window.location.origin}/trips/join/${group.id}#invite=${result.invite_token}` });
  const refresh = async () => { setRefreshing(true); try { await onRefresh(); setStatus('Trip is up to date.'); } catch (e) { setStatus(e.message); } finally { setRefreshing(false); } };
  const expenses = group.expenses.filter((e) => `${e.description} ${e.notes} ${personName(group, e.paid_by)} ${categoryNames[e.category]}`.toLowerCase().includes(query.toLowerCase())).sort((a, b) => b.date.localeCompare(a.date) || b.created_at.localeCompare(a.created_at));
  return <>
    <div className="trips-breadcrumb"><Link to="/trips"><ArrowLeft size={15} /> All trips</Link><button aria-label="Refresh trip" disabled={refreshing} onClick={refresh}><RefreshCw size={14} className={refreshing ? 'trips-refreshing' : ''} aria-hidden="true" /> {refreshing ? 'Refreshing…' : 'Refresh'}</button></div>
    <section className="trips-heading"><div><h1>{group.name}</h1><p className="trips-muted">{group.members.length} {group.members.length === 1 ? 'person' : 'people'} · {group.currency}</p></div><Button variant="primary" onClick={() => setModal({ type: 'expense' })}><Plus size={17} /> Add expense</Button></section>
    <div role="status" aria-live="polite" className="trips-status">{status}</div>
    <section className="trips-totals" aria-label="Trip summary"><div><span className="trips-icon-label"><ReceiptText size={14} aria-hidden="true" />Total expenses</span><strong>{money(group.total_minor, group.currency)}</strong><small>{group.expenses.length} {group.expenses.length === 1 ? 'expense' : 'expenses'}</small></div><div><span className="trips-icon-label"><Wallet size={14} aria-hidden="true" />{myBalance < 0 ? 'You owe' : myBalance > 0 ? 'You’re owed' : 'Your balance'}</span><strong className={myBalance > 0 ? 'trips-positive' : ''}>{money(Math.abs(myBalance), group.currency)}</strong></div></section>
    <nav className="trips-tabs" aria-label="Trip sections">{Object.entries(sectionIcons).map(([name, Icon]) => <button key={name} aria-pressed={tab === name} onClick={() => setTab(name)}><Icon size={15} aria-hidden="true" />{name}{name === 'Expenses' && <span>{group.expenses.length}</span>}</button>)}</nav>
    <div className={`trips-columns trips-columns--${tab.toLowerCase()}`}><section className="trips-ledger" aria-label={tab}>
      {tab === 'Expenses' && <><div className="trips-panel-heading"><SectionHeading icon={ReceiptText}>Expenses</SectionHeading><label className="trips-search"><Search size={15} /><input aria-label="Search expenses" placeholder="Search expenses" value={query} onChange={(e) => setQuery(e.target.value)} /></label></div>
        {!expenses.length ? <div className="trips-empty"><h3>{query ? 'No matching expenses' : 'No expenses yet'}</h3><p>{query ? 'Try a different search.' : 'Add an expense to start splitting costs.'}</p></div>
          : <ul className="trips-expense-list">{expenses.map((expense) => <li key={expense.id}><button className="trips-expense" aria-label={`Edit ${expenseContext(group, expense)}`} onClick={() => setModal({ type: 'expense', expense })}><ExpenseCategory category={expense.category} /><span className="trips-expense-detail"><strong>{expense.description}</strong><small>{personName(group, expense.paid_by)} paid · {shortDate(expense.date)} · {Object.keys(expense.shares).length} {Object.keys(expense.shares).length === 1 ? 'person' : 'people'}</small></span><span className="trips-expense-amount"><strong>{money(expense.amount_minor, group.currency)}</strong><small>{expense.split_mode === 'equal' ? 'equal' : 'exact'}</small></span></button><button className="trips-text-button trips-remove" aria-label={`Delete ${expenseContext(group, expense)}`} onClick={() => setModal({ type: 'delete_expense', item: expense })}><Trash2 size={13} aria-hidden="true" />Delete</button></li>)}</ul>}</>}
      {tab === 'Balances' && <><div className="trips-panel-heading"><SectionHeading icon={Banknote}>Suggested payments</SectionHeading><Button onClick={() => setModal({ type: 'repayment' })} disabled={group.members.length < 2}><Banknote size={15} aria-hidden="true" />Record repayment</Button></div><p className="trips-muted">These payments settle the whole group. You may pay someone different from the person who covered an expense. Record a repayment after it happens.</p>
        {breakdown && <details className="trips-calculation"><summary>Your balance breakdown</summary>
          <dl className="trips-calculation-totals"><div><dt>You paid for expenses</dt><dd>{money(breakdown.paid, group.currency)}</dd></div><div><dt>Your share of expenses</dt><dd>{money(breakdown.share, group.currency)}</dd></div>
            {!!breakdown.sent && <div><dt>Repayments you sent</dt><dd>{money(breakdown.sent, group.currency)}</dd></div>}{!!breakdown.received && <div><dt>Repayments you received</dt><dd>{money(breakdown.received, group.currency)}</dd></div>}
            <div><dt>{breakdown.net < 0 ? 'You owe in total' : breakdown.net > 0 ? 'You are owed in total' : 'Your net balance'}</dt><dd>{money(Math.abs(breakdown.net), group.currency)}</dd></div></dl>
          <h3>Your direct balances</h3><p className="trips-muted">These explain who covered whom, including repayments. They can offset across the group, even when your total is settled.</p>
          {!breakdown.direct.length ? <p className="trips-muted">No direct balances remaining.</p> : <ul className="trips-direct-balances">{breakdown.direct.map(row => <li key={row.member_id}><span>{personName(group, row.member_id)}</span><strong>{row.amount_minor > 0 ? 'You owe' : 'Owes you'} {money(Math.abs(row.amount_minor), group.currency)}</strong></li>)}</ul>}
        </details>}
        {!group.transfers.length && <p className="trips-muted">All balances are settled.</p>}
        {group.transfers.map((transfer) => <div className="trips-transfer" key={`${transfer.from_member}-${transfer.to_member}`}><p><strong>{personName(group, transfer.from_member)}</strong><ArrowRight size={16} /><strong>{personName(group, transfer.to_member)}</strong></p><strong>{money(transfer.amount_minor, group.currency)}</strong><Button aria-label={`Record repayment from ${personName(group, transfer.from_member)} to ${personName(group, transfer.to_member)}`} onClick={() => setModal({ type: 'repayment', suggestion: transfer })}><Check size={15} aria-hidden="true" />Record payment</Button></div>)}
        <h3 className="trips-subheading">Recorded repayments</h3>{!group.repayments.length && <p className="trips-muted">No repayments recorded yet.</p>}
        {group.repayments.slice().reverse().map((p) => <div className="trips-repayment" key={p.id}><div><strong>{personName(group, p.from_member)} → {personName(group, p.to_member)}</strong><small>{shortDate(p.date)}{p.notes && ` · ${p.notes}`}</small></div><strong>{money(p.amount_minor, group.currency)}</strong><button className="trips-text-button" aria-label={`Remove repayment from ${personName(group, p.from_member)} to ${personName(group, p.to_member)}`} onClick={() => setModal({ type: 'delete_repayment', item: p })}>Remove</button></div>)}</>}
      {tab === 'People' && <><div className="trips-panel-heading"><SectionHeading icon={UsersRound}>People</SectionHeading>{group.owner_id === user.id && <Button onClick={() => setModal({ type: 'member' })}><UserPlus size={16} aria-hidden="true" /> Add person</Button>}</div><p className="trips-muted">Everyone on the trip can add and edit expenses.</p>{group.members.map((m, index) => <div className="trips-person" key={m.id}><Avatar member={m} index={index} /><div><strong>{memberName(m)}{m.user_id === user.id ? ' (you)' : ''}</strong><small>{m.user_id === group.owner_id ? 'Trip creator' : m.user_id ? 'Joined' : 'Not joined yet'}</small></div>{!m.user_id && group.owner_id === user.id && <Button onClick={() => setModal({ type: 'generate_invite', member: m })}><Link2 size={14} aria-hidden="true" />Invite</Button>}</div>)}</>}
      {tab === 'Activity' && <><div className="trips-panel-heading"><SectionHeading icon={History}>Activity</SectionHeading></div>{!group.activity.length && <p className="trips-muted">No activity yet.</p>}<ol className="trips-activity">{group.activity.map((a) => <li key={a.id}><span className="trips-activity-marker" aria-hidden="true"><History size={14} /></span><div><strong>{a.summary}</strong><small>{memberName(group.members.find((m) => m.user_id === a.user_id))} · {new Date(a.at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</small></div></li>)}</ol></>}
    </section><aside className="trips-balance-card" aria-label="Member balances"><SectionHeading icon={Wallet}>Balances</SectionHeading>{group.members.map((m, i) => <div className="trips-balance-row" key={m.id}><Avatar member={m} index={i} /><span>{memberName(m)}</span><strong className={group.balances[m.id] > 0 ? 'trips-positive' : ''}><small>{group.balances[m.id] < 0 ? 'owes' : group.balances[m.id] > 0 ? 'is owed' : 'settled'}</small>{group.balances[m.id] !== 0 && money(Math.abs(group.balances[m.id]), group.currency)}</strong></div>)}</aside></div>
    {modal && <Modal title={{ expense: modal.expense ? 'Edit expense' : 'Add expense', member: 'Add person', repayment: 'Record repayment', invitation: 'Invite link', generate_invite: `Invite ${modal.member?.name}`, delete_expense: 'Delete this expense?', delete_repayment: 'Remove this repayment?' }[modal.type]} onClose={() => setModal(null)}>
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
  if (joinId) return <section className="trips-join"><h1>Join trip</h1><p>Accept your invitation to view and add expenses.</p><Form submit="Join trip" onCancel={() => navigate('/trips')} onSubmit={async () => {
    if (!invitation) throw new Error('The invitation link is missing its secret. Open the original link again.');
    const result = await request(`/groups/${joinId}/join`, 'POST', { invite_token: invitation });
    clearInvitation(joinId); navigate(`/trips/${result.id}`);
  }}><p className="trips-muted">Joining as {auth.profile?.display_name || auth.user.user_metadata?.full_name || auth.user.email}.</p></Form></section>;
  if (loading) return <p className="trips-loading" role="status">Loading…</p>;
  if (error) return <div className="trips-empty"><p role="alert">{error}</p><Button onClick={async () => { setError(''); setLoading(true); try { await load(); } catch (e) { setError(e.message); } finally { setLoading(false); } }}>Try again</Button><Link to="/trips">All trips</Link></div>;
  if (tripId && group) return <TripView key={group.id} group={group} user={auth.user} request={request} onUpdated={setGroup} onRefresh={load} />;
  return <><section className="trips-heading trips-heading--home"><h1>Your trips</h1><div className="trips-home-actions"><Button onClick={() => setImporting(true)}><Download size={15} aria-hidden="true" /> Import from Splitwise</Button><Button variant="primary" onClick={() => setCreating(true)}><Plus size={17} /> New trip</Button></div></section>
    {!groups.length ? <div className="trips-empty"><h2>No trips yet</h2><p>Create a trip or import one from Splitwise.</p></div>
      : <div className="trips-trip-list">{groups.map((g) => { const myId = g.members.find((m) => m.user_id === auth.user.id)?.id; const balance = g.balances[myId] || 0; return <Link className="trips-trip-row" to={`/trips/${g.id}`} key={g.id}><span className="trips-trip-icon" aria-hidden="true"><Luggage size={20} /></span><div className="trips-trip-row-main"><h2>{g.name}</h2><p>{g.members.length} {g.members.length === 1 ? 'person' : 'people'} · {g.expenses.length} {g.expenses.length === 1 ? 'expense' : 'expenses'} · {g.currency}</p></div><div className="trips-trip-row-balance"><strong className={balance > 0 ? 'trips-positive' : ''}>{balance === 0 ? 'Settled' : `${balance > 0 ? 'You’re owed' : 'You owe'} ${money(Math.abs(balance), g.currency)}`}</strong><small>{money(g.total_minor, g.currency)} total</small></div><ArrowRight size={16} aria-hidden="true" /></Link>; })}</div>}
    {creating && <Modal title="New trip" onClose={() => setCreating(false)}><CreateTrip user={auth.user} profile={auth.profile} onCancel={() => setCreating(false)} onSave={async (payload) => { const result = await request('/groups', 'POST', payload); setCreating(false); navigate(`/trips/${result.id}`); }} /></Modal>}
    {importing && <Modal title="Import from Splitwise" onClose={() => setImporting(false)}><ImportTrip request={request} onCancel={() => setImporting(false)} onImported={group => { setImporting(false); navigate(`/trips/${group.id}`); }} /></Modal>}
  </>;
}

export default function TripsApp() {
  const auth = useTripsAuth();
  const tripId = useMatch('/trips/:tripId')?.params.tripId;
  const joinId = useMatch('/trips/join/:tripId')?.params.tripId;
  const workspaceKey = `${auth.user?.id}:${joinId || tripId || 'home'}`;
  const headerProfile = auth.profile || { user_id: auth.user?.id,
    display_name: auth.user?.user_metadata?.full_name || auth.user?.user_metadata?.name || auth.user?.email || 'Me',
    avatar_url: auth.user?.user_metadata?.avatar_url || auth.user?.user_metadata?.picture };
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
  return <div className="cc-page trips"><a href="#trips-main" className="trips-skip">Skip to trip</a><header className="trips-navbar"><Link to="/" className="trips-home-link" aria-label="Cozy Commons home"><span className="trips-commons-mark" aria-hidden="true"><span>cozy</span><small>commons</small></span></Link><Link to="/trips" className="trips-wordmark"><span className="trips-logo" aria-hidden="true"><Luggage size={17} /></span>Cozy Trips</Link><div className="trips-account">{auth.user && <><span className="trips-account-identity" aria-label={`Signed in as ${headerProfile.display_name}`}><PlayerAvatar profile={headerProfile} size={32} linkToProfile={false} /><span className="trips-account-name">{headerProfile.display_name}</span></span><Button variant="ghost" aria-label="Sign out" onClick={async () => { try { await auth.signOut(); } catch (e) { setError(e.message); } }}><LogOut size={14} aria-hidden="true" /><span className="trips-signout-label">Sign out</span></Button></>}{localDemo && <span className="trips-demo-badge">LOCAL</span>}</div></header>
    {(error || auth.error) && <p className="trips-error" role="alert">{error || auth.error}</p>}
    <main id="trips-main">{auth.loading ? <p className="trips-loading" role="status">Loading…</p> : auth.user ? <Workspace key={workspaceKey} auth={auth} tripId={tripId} joinId={joinId} invitation={invitation.current} /> : <section className="trips-welcome"><h1>Cozy Trips</h1><p className="trips-intro">Split expenses and track balances with friends.</p>{joinId && <p>Sign in to accept your trip invitation.</p>}{!localDemo && <><Button variant="primary" disabled={signingIn} onClick={() => signIn()}>Continue with Google <ArrowRight size={17} /></Button><p className="trips-muted">Use your Cozy Commons account.</p></>}
      {localDemo && <div className="trips-demo"><p className="trips-eyebrow">Local test accounts</p><div>{['Matt', 'Alex', 'Jamie'].map((name) => <Button variant={name === 'Matt' ? 'primary' : 'secondary'} key={name} disabled={signingIn} onClick={() => signIn(name)}>Continue as {name}</Button>)}</div></div>}</section>}</main>
  </div>;
}
