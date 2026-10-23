import React, { useEffect, useRef, useState } from 'react';
import { Link, useSearchParams } from 'react-router-dom';
import { ArrowLeft, HandCoins, History, Plus, ReceiptText, RefreshCw, Search, UsersRound } from 'lucide-react';
import { money, shortDate } from './money.js';
import { Avatar, AvatarStack, Button, Form, Modal } from './ui.jsx';
import { findMember, firstName, memberName, myMember } from './people.js';
import { ExpenseForm, categoryOf } from './ExpenseForm.jsx';
import { BalancesPanel, RepaymentForm, VenmoReview } from './Settle.jsx';
import { AddPeopleForm, InviteLinks, PeoplePanel, VenmoForm } from './People.jsx';

const tabs = [
  { key: 'expenses', label: 'Expenses', icon: ReceiptText },
  { key: 'balances', label: 'Balances', icon: HandCoins },
  { key: 'people', label: 'People', icon: UsersRound },
  { key: 'activity', label: 'Activity', icon: History },
];
const prefillKeys = ['add', 'description', 'amount', 'paid_by', 'category', 'participants'];
const CONFLICT = 'Someone changed this trip while you were editing. The latest version is loaded and your entry is kept. Check it, then save again.';

const expenseContext = (group, expense) => `${expense.description}, ${money(expense.amount_minor, group.currency)} paid by ${memberName(findMember(group, expense.paid_by))} on ${expense.date}`;

function myEffect(expense, meId) {
  const share = expense.shares[meId] || 0;
  if (expense.paid_by === meId) return expense.amount_minor - share ? { text: 'you lent', amount: expense.amount_minor - share, tone: 'positive' } : { text: 'just you' };
  return share ? { text: 'you borrowed', amount: share, tone: 'owe' } : { text: 'not involved' };
}

function ExpenseList({ group, me, query, onEdit }) {
  const needle = query.trim().toLowerCase();
  const expenses = group.expenses
    .filter((e) => !needle || `${e.description} ${e.notes} ${memberName(findMember(group, e.paid_by))} ${categoryOf(e.category).label}`.toLowerCase().includes(needle))
    .sort((a, b) => b.date.localeCompare(a.date) || b.created_at.localeCompare(a.created_at));
  if (!expenses.length) return <div className="trips-empty"><p>{needle ? 'No matching expenses.' : 'No expenses yet.'}</p></div>;
  const days = [];
  for (const expense of expenses) {
    if (days.at(-1)?.date !== expense.date) days.push({ date: expense.date, items: [] });
    days.at(-1).items.push(expense);
  }
  return days.map(({ date, items }) => <section className="trips-day" key={date} aria-label={shortDate(date)}>
    <h3 className="trips-day-label">{shortDate(date)}</h3>
    <ul className="trips-expense-list">{items.map((expense) => {
      const { icon: Icon, color } = categoryOf(expense.category);
      const payer = findMember(group, expense.paid_by);
      const effect = me ? myEffect(expense, me.id) : null;
      return <li key={expense.id}><button className="trips-expense" aria-label={`Edit ${expenseContext(group, expense)}`} onClick={() => onEdit(expense)}>
        <span className="trips-category" style={{ '--chip': color }} aria-hidden="true"><Icon size={17} /></span>
        <span className="trips-expense-detail"><strong>{expense.description}</strong>
          <small><Avatar member={payer} size={16} />{payer?.id === me?.id ? 'You' : firstName(payer)} paid · {Object.keys(expense.shares).length} {Object.keys(expense.shares).length === 1 ? 'person' : 'people'}</small></span>
        <span className="trips-expense-amount"><strong>{money(expense.amount_minor, group.currency)}</strong>
          {effect && <small className={effect.tone ? `trips-${effect.tone}` : ''}>{effect.text}{effect.amount ? ` ${money(effect.amount, group.currency)}` : ''}</small>}</span>
      </button></li>;
    })}</ul>
  </section>);
}

export default function TripView({ group, user, profile, request, onUpdated, onRefresh, onEditProfile }) {
  const [params, setParams] = useSearchParams();
  const tab = tabs.find((t) => t.key === params.get('tab'))?.key || 'expenses';
  const [query, setQuery] = useState('');
  const [notice, setNotice] = useState(null);
  const [refreshing, setRefreshing] = useState(false);
  // Every dialog keeps the revision it was opened from, so a background refresh never silently rebases a draft.
  // Agents and shortcuts can open a prefilled, unsaved expense: ?add=expense&description=Dinner&amount=42.50
  const [modal, setModalState] = useState(() => params.get('add') === 'expense' ? { type: 'expense', revision: group.revision, initial: {
    description: params.get('description') || '', amount: params.get('amount') || '', paid_by: params.get('paid_by'),
    category: params.get('category') || undefined, participants: params.get('participants')?.split(',') } } : null);
  const latest = useRef(group);
  latest.current = group;
  const setModal = (next) => setModalState(next && { revision: latest.current.revision, ...next });
  const alive = useRef(true);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  useEffect(() => {
    if (prefillKeys.some((key) => params.has(key))) setParams((next) => { prefillKeys.forEach((key) => next.delete(key)); return next; }, { replace: true });
  }, []); // eslint-disable-line react-hooks/exhaustive-deps

  const me = myMember(group, user.id);
  const setTab = (key) => setParams((next) => { next.set('tab', key); return next; }, { replace: true });
  const close = () => setModal(null);

  // Every write is compare-and-swap. On conflict: load the latest trip, keep the open draft, and require an
  // explicit second save against the newly shown version.
  const update = async (path, method, payload, message, undo) => {
    let result;
    try {
      result = await request(`/groups/${group.id}${path}`, method, payload);
    } catch (error) {
      if (error.status === 409 && alive.current) {
        const fresh = await onRefresh().catch(() => null);
        if (fresh && alive.current) setModalState((current) => current && { ...current, revision: fresh.revision, conflict: true });
        throw new Error(CONFLICT);
      }
      throw error;
    }
    if (!alive.current) return result;
    onUpdated(result.group || result);
    setNotice({ message, undo });
    setModalState(null);
    return result;
  };
  const formGroup = modal ? { ...group, revision: modal.revision } : group;
  const refresh = async () => {
    setRefreshing(true);
    try { await onRefresh(); setNotice({ message: 'Up to date.' }); } catch (e) { setNotice({ message: e.message }); } finally { if (alive.current) setRefreshing(false); }
  };
  const recordPayment = (payload) => update('/repayments', 'POST', payload,
    `Recorded ${memberName(findMember(group, payload.from_member))} → ${memberName(findMember(group, payload.to_member))}, ${money(payload.amount_minor, group.currency)}.`,
    () => update(`/repayments/${payload.id}`, 'DELETE', { revision: latest.current.revision }, 'Payment removed.'));
  const addPeople = async (names) => {
    // Sequential adds; a retry after a partial failure skips people who were already added.
    const existing = new Set(latest.current.members.map((m) => m.name.toLowerCase()));
    const fresh = names.filter((name) => !existing.has(name.toLowerCase()));
    if (!fresh.length) throw new Error('Everyone listed is already on this trip.');
    const links = [];
    let revision = latest.current.revision;
    for (const name of fresh) {
      let result;
      try {
        result = await request(`/groups/${group.id}/members`, 'POST', { name, revision });
      } catch (error) {
        if (error.status === 409 && alive.current) await onRefresh().catch(() => {});
        throw new Error(`${links.length ? `Added ${links.map((l) => l.name).join(', ')}. ` : ''}Could not add ${name}: ${error.message}`);
      }
      revision = result.group.revision;
      if (!alive.current) return;
      onUpdated(result.group);
      links.push({ name, link: `${window.location.origin}/trips/join/${group.id}#invite=${result.invite_token}` });
    }
    setNotice({ message: `Added ${fresh.join(', ')}.` });
    setModal({ type: 'invites', links });
  };
  const titles = { expense: modal?.expense ? 'Edit expense' : 'Add expense', repayment: 'Record a payment', venmo: modal?.role === 'request' ? 'Request with Venmo' : 'Pay with Venmo',
    people: 'Add people', invites: 'Invite links', invite: `Invite ${modal?.member ? memberName(modal.member) : ''}`, member_venmo: `Venmo for ${modal?.member ? memberName(modal.member) : ''}`,
    delete_expense: 'Delete this expense?', delete_repayment: 'Undo this payment?' };
  const myBalance = group.balances[me?.id] || 0;

  return <div className={`trips-trip trips-trip--${tab}`}>
    <div className="trips-breadcrumb"><Link to="/trips"><ArrowLeft size={15} aria-hidden="true" />Trips</Link>
      <button aria-label="Refresh trip" disabled={refreshing} onClick={refresh}><RefreshCw size={14} className={refreshing ? 'trips-refreshing' : ''} aria-hidden="true" />{refreshing ? 'Refreshing…' : 'Refresh'}</button></div>
    <section className="trips-heading">
      <div><h1 tabIndex={-1}>{group.name}</h1>
        <p className="trips-trip-meta"><AvatarStack members={group.members} />{group.members.length} {group.members.length === 1 ? 'person' : 'people'} · {money(group.total_minor, group.currency)} total</p></div>
      <div className="trips-heading-actions">
        {me && tab !== 'balances' && <button className={`trips-balance-pill trips-balance-pill--${myBalance < 0 ? 'owe' : myBalance > 0 ? 'owed' : 'even'}`} onClick={() => setTab('balances')}>
          {myBalance < 0 ? `You owe ${money(-myBalance, group.currency)}` : myBalance > 0 ? `You’re owed ${money(myBalance, group.currency)}` : 'Settled up'}</button>}
        <Button variant="primary" className="trips-add" onClick={() => setModal({ type: 'expense' })}><Plus size={18} aria-hidden="true" /><span>Add expense</span></Button>
      </div>
    </section>
    <div role="status" aria-live="polite" className="trips-notice">{notice && <>{notice.message}{notice.undo && <button className="trips-text-button" onClick={async () => {
      const undo = notice.undo; setNotice(null);
      try { await undo(); } catch (e) { setNotice({ message: e.message }); }
    }}>Undo</button>}</>}</div>

    <nav className="trips-tabs" role="tablist" aria-label="Trip sections">{tabs.map(({ key, label, icon: Icon }) => <button key={key} role="tab" id={`trips-tab-${key}`} aria-controls="trips-panel" aria-selected={tab === key} onClick={() => setTab(key)}>
      <Icon size={18} aria-hidden="true" /><span>{label}</span>{key === 'expenses' && <span className="trips-count">{group.expenses.length}</span>}</button>)}</nav>

    <div className={`trips-columns trips-columns--${tab}`}>
      <section className="trips-ledger" id="trips-panel" role="tabpanel" aria-labelledby={`trips-tab-${tab}`}>
        {tab === 'expenses' && <>
          <div className="trips-panel-heading"><h2 className="trips-section-heading"><ReceiptText size={16} aria-hidden="true" />Expenses</h2>
            <label className="trips-search"><Search size={15} aria-hidden="true" /><input type="search" name="search" aria-label="Search expenses" placeholder="Search" value={query} onChange={(e) => setQuery(e.target.value)} /></label></div>
          <ExpenseList group={group} me={me} query={query} onEdit={(expense) => setModal({ type: 'expense', expense })} />
        </>}
        {tab === 'balances' && <BalancesPanel group={group} me={me} profile={profile} onEditProfile={onEditProfile}
          onVenmo={(transfer, role) => setModal({ type: 'venmo', transfer, role })}
          onRecord={(suggestion) => setModal({ type: 'repayment', suggestion })}
          onRemoveRepayment={(item) => setModal({ type: 'delete_repayment', item })} />}
        {tab === 'people' && <PeoplePanel group={group} user={user} onEditProfile={onEditProfile} onAdd={() => setModal({ type: 'people' })}
          onInvite={(member) => setModal({ type: 'invite', member })} onEditVenmo={(member) => setModal({ type: 'member_venmo', member })} />}
        {tab === 'activity' && <>
          <div className="trips-panel-heading"><h2 className="trips-section-heading"><History size={16} aria-hidden="true" />Activity</h2></div>
          {!group.activity.length ? <p className="trips-muted">Nothing yet.</p> : <ol className="trips-activity">{group.activity.map((a) => {
            const actor = group.members.find((m) => m.user_id === a.user_id);
            return <li key={a.id}><Avatar member={actor || { name: '?' }} size={28} /><div><strong>{a.summary}</strong>
              <small>{actor ? memberName(actor) : 'Someone'} · {new Date(a.at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}</small></div></li>;
          })}</ol>}
        </>}
      </section>
      <aside className="trips-balance-card" aria-label="Member balances"><h2 className="trips-section-heading"><HandCoins size={16} aria-hidden="true" />Balances</h2>
        {group.members.map((m) => { const balance = group.balances[m.id] || 0; return <div className="trips-balance-row" key={m.id}><Avatar member={m} size={28} /><span>{memberName(m)}</span>
          <strong className={balance > 0 ? 'trips-positive' : balance < 0 ? 'trips-owe' : ''}><small>{balance < 0 ? 'owes' : balance > 0 ? 'gets back' : 'settled'}</small>{balance !== 0 && money(Math.abs(balance), group.currency)}</strong></div>; })}
      </aside>
    </div>

    {modal && <Modal title={titles[modal.type]} onClose={close}>
      {modal.type === 'expense' && <ExpenseForm group={formGroup} user={user} expense={modal.expense} initial={modal.initial} conflict={modal.conflict && modal.expense ? { latest: group.expenses.find((e) => e.id === modal.expense.id) || null } : null} onCancel={close}
        onDelete={() => setModal({ type: 'delete_expense', item: modal.expense })}
        onSave={(payload) => update(`/expenses${modal.expense ? `/${modal.expense.id}` : ''}`, modal.expense ? 'PUT' : 'POST', payload, modal.expense ? 'Expense updated.' : `Added ${payload.description}.`)} />}
      {modal.type === 'repayment' && <RepaymentForm group={formGroup} suggestion={modal.suggestion} onCancel={close} onSave={recordPayment} />}
      {modal.type === 'venmo' && <VenmoReview group={formGroup} transfer={modal.transfer} role={modal.role} onCancel={close} onRecord={recordPayment}
        onEditHandles={group.owner_id === user.id ? () => { close(); setTab('people'); } : findMember(group, modal.role === 'pay' ? modal.transfer.to_member : modal.transfer.from_member)?.user_id === user.id ? onEditProfile : null} />}
      {modal.type === 'people' && <AddPeopleForm onCancel={close} onSave={addPeople} />}
      {modal.type === 'invites' && <InviteLinks links={modal.links} onClose={close} />}
      {modal.type === 'invite' && <Form submit="Create invite link" onCancel={close} onSubmit={async () => {
        const result = await update(`/members/${modal.member.id}/invite`, 'POST', { revision: modal.revision }, 'Invite link ready.');
        if (alive.current) setModal({ type: 'invites', links: [{ name: memberName(modal.member), link: `${window.location.origin}/trips/join/${group.id}#invite=${result.invite_token}` }] });
      }}><p>A new one-use link for {memberName(modal.member)}. Older links for them stop working.</p></Form>}
      {modal.type === 'member_venmo' && <VenmoForm initial={modal.member.venmo_username} onCancel={close}
        hint={`Only for this trip, until ${firstName(modal.member)} joins and adds their own.`}
        onSave={(username) => update(`/members/${modal.member.id}/venmo`, 'PUT', { venmo_username: username, revision: modal.revision }, username ? `Saved @${username}.` : 'Venmo removed.')} />}
      {modal.type === 'delete_expense' && <Form destructive submit="Delete expense" onCancel={close} onSubmit={() => update(`/expenses/${modal.item.id}`, 'DELETE', { revision: modal.revision }, `Deleted ${modal.item.description}.`)}>
        <p>{modal.item.description} · {money(modal.item.amount_minor, group.currency)}</p><p className="trips-muted">Everyone’s balance will update.</p></Form>}
      {modal.type === 'delete_repayment' && <Form destructive submit="Undo payment" onCancel={close} onSubmit={() => update(`/repayments/${modal.item.id}`, 'DELETE', { revision: modal.revision }, 'Payment removed.')}>
        <p>{memberName(findMember(group, modal.item.from_member))} → {memberName(findMember(group, modal.item.to_member))} · {money(modal.item.amount_minor, group.currency)}</p></Form>}
    </Modal>}
  </div>;
}
