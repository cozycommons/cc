import React, { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useSearchParams } from 'react-router-dom';
import { ArrowLeft, HandCoins, History, Plus, ReceiptText, RefreshCw, RotateCcw, Search, UsersRound } from 'lucide-react';
import { money, shortDate } from './money.js';
import { Avatar, AvatarStack, Button, Form, Modal } from './ui.jsx';
import { Bowl, Tent, TripStamp, isNiteharts } from './doodles.jsx';
import { findMember, firstName, memberName, myMember } from './people.js';
import { ExpenseDetail, ExpenseForm, categoryOf, payerLabel, savedSummary } from './ExpenseForm.jsx';
import { paidAmounts, payersOf } from './balances.js';
import { BalancesPanel, RepaymentForm, VenmoReview } from './Settle.jsx';
import { AddPeopleForm, InviteLinks, PeoplePanel, PersonSheet, RenameForm, TripSettings, VenmoForm } from './People.jsx';
import LinkAccounts from './LinkAccounts.jsx';

const tabs = [
  { key: 'expenses', label: 'Expenses', icon: ReceiptText },
  { key: 'balances', label: 'Balances', icon: HandCoins },
  { key: 'people', label: 'People', icon: UsersRound },
  { key: 'activity', label: 'Activity', icon: History },
];
const prefillKeys = ['add', 'description', 'amount', 'paid_by', 'category', 'participants'];
const CONFLICT = 'Someone changed this trip while you were editing. The latest version is loaded and your entry is kept. Check it, then save again.';
// Other people's changes show up without a manual refresh while the trip is open.
const POLL_MS = 30000;

const expenseContext = (group, expense) => `${expense.description}, ${money(expense.amount_minor, group.currency)} paid by ${payersOf(group, expense).map(([m]) => memberName(m)).join(' and ')} on ${expense.date}`;

function myEffect(expense, meId) {
  const share = expense.shares[meId] || 0;
  const paid = paidAmounts(expense)[meId] || 0;
  if (paid > share) return { text: 'you lent', amount: paid - share, tone: 'positive' };
  if (share > paid) return { text: 'you borrowed', amount: share - paid, tone: 'owe' };
  return { text: !paid ? 'not involved' : paid === expense.amount_minor ? 'just you' : 'you’re even' };
}

function ExpenseRow({ group, expense, me, fresh, onOpen }) {
  const { icon: Icon, color } = categoryOf(expense.category);
  const payer = findMember(group, expense.paid_by);
  const effect = me ? myEffect(expense, me.id) : null;
  const people = Object.keys(expense.shares).length;
  return <li className={expense.id === fresh ? 'trips-row--new' : undefined}><button className="trips-expense" aria-label={`Open ${expenseContext(group, expense)}`} onClick={() => onOpen(expense)}>
    <span className="trips-category" style={{ '--chip': color }} aria-hidden="true"><Icon size={22} /></span>
    <span className="trips-expense-detail"><strong>{expense.description}</strong>
      <small><Avatar member={payer} size={16} />{payerLabel(group, expense, me?.id)} paid · {people} {people === 1 ? 'person' : 'people'}</small></span>
    <span className="trips-expense-amount"><strong>{money(expense.amount_minor, group.currency)}</strong>
      {effect && <small className={effect.tone ? `trips-${effect.tone}` : ''}>{effect.text}{effect.amount ? ` ${money(effect.amount, group.currency)}` : ''}</small>}</span>
  </button></li>;
}

// Payments sit in the same feed as expenses, like Splitwise, so the history reads in one place.
function PaymentRow({ group, payment, me, onOpen }) {
  const from = findMember(group, payment.from_member);
  const to = findMember(group, payment.to_member);
  const name = (m) => (m?.id === me?.id ? 'You' : firstName(m));
  const mine = me && (payment.from_member === me.id ? 'you paid' : payment.to_member === me.id ? 'you received' : null);
  return <li><button className="trips-expense trips-expense--payment" aria-label={`Payment: ${memberName(from)} paid ${memberName(to)} ${money(payment.amount_minor, group.currency)} on ${payment.date}`} onClick={() => onOpen(payment)}>
    <span className="trips-category trips-category--payment" aria-hidden="true"><HandCoins size={20} /></span>
    <span className="trips-expense-detail"><strong>{name(from)} paid {name(to) === 'You' ? 'you' : name(to)}</strong>
      <small>Payment{payment.notes ? ` · ${payment.notes}` : ''}</small></span>
    <span className="trips-expense-amount"><strong>{money(payment.amount_minor, group.currency)}</strong>{mine && <small>{mine}</small>}</span>
  </button></li>;
}

function Feed({ group, me, query, fresh, onOpenExpense, onOpenPayment }) {
  const needle = query.trim().toLowerCase();
  const name = (id) => memberName(findMember(group, id));
  const items = [
    ...group.expenses.filter((e) => !needle || `${e.description} ${e.notes} ${Object.keys(paidAmounts(e)).map(name).join(' ')} ${categoryOf(e.category).label}`.toLowerCase().includes(needle))
      .map((e) => ({ kind: 'expense', item: e, at: e.created_at || '' })),
    ...group.repayments.filter((p) => !needle || `payment ${p.notes} ${name(p.from_member)} ${name(p.to_member)}`.toLowerCase().includes(needle))
      .map((p) => ({ kind: 'payment', item: p, at: p.created_at || '' })),
  ].sort((a, b) => b.item.date.localeCompare(a.item.date) || b.at.localeCompare(a.at));
  if (!items.length) return <div className="trips-empty">{!needle && <Bowl size={64} className="trips-empty-doodle" />}<p>{needle ? 'Nothing matches that.' : 'Nothing spent yet. Add the first receipt.'}</p></div>;
  const days = [];
  for (const entry of items) {
    if (days.at(-1)?.date !== entry.item.date) days.push({ date: entry.item.date, entries: [] });
    days.at(-1).entries.push(entry);
  }
  return days.map(({ date, entries }) => <section className="trips-day" key={date} aria-label={shortDate(date)}>
    <h3 className="trips-day-label">{shortDate(date)}</h3>
    <ul className="trips-expense-list">{entries.map(({ kind, item }) => kind === 'expense'
      ? <ExpenseRow key={item.id} group={group} expense={item} me={me} fresh={fresh} onOpen={onOpenExpense} />
      : <PaymentRow key={item.id} group={group} payment={item} me={me} onOpen={onOpenPayment} />)}</ul>
  </section>);
}

function ActivityList({ group, me, onOpenExpense, onRestore }) {
  if (!group.activity.length) return <div className="trips-empty"><Tent size={64} className="trips-empty-doodle" /><p>Quiet so far.</p></div>;
  return <ol className="trips-activity">{group.activity.map((a) => {
    const actor = group.members.find((m) => m.user_id === a.user_id);
    const current = a.item_id && group.expenses.find((e) => e.id === a.item_id);
    // A deleted expense keeps its snapshot in the activity row, so it can come back.
    const onTrip = (id) => group.members.some((m) => m.id === id);
    const restorable = a.kind === 'delete_expense' && a.expense && !current
      && Object.keys(paidAmounts(a.expense)).every(onTrip) && Object.keys(a.expense.shares).every(onTrip)
      && !group.activity.some((later) => later.kind === 'delete_expense' && later.item_id === a.item_id && later.at > a.at);
    const shown = current || a.expense;
    const effect = me && shown?.shares && a.kind !== 'delete_expense' ? myEffect(shown, me.id) : null;
    const body = <><Avatar member={actor || { name: '?' }} size={28} /><div><strong>{a.summary}</strong>
      <small>{actor ? memberName(actor) : 'Someone'} · {new Date(a.at).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' })}
        {effect?.amount ? <> · <span className={`trips-${effect.tone}`}>{effect.text} {money(effect.amount, group.currency)}</span></> : null}</small></div>
      {a.amount_minor ? <span className="trips-activity-amount">{money(a.amount_minor, group.currency)}</span> : null}</>;
    return <li key={a.id}>
      {current ? <button type="button" className="trips-activity-row" onClick={() => onOpenExpense(current)} aria-label={`${a.summary}. Open it`}>{body}</button>
        : <div className="trips-activity-row">{body}</div>}
      {restorable && <button type="button" className="trips-text-button trips-activity-restore" onClick={() => onRestore(a.expense)}><RotateCcw size={14} aria-hidden="true" />Restore</button>}
    </li>;
  })}</ol>;
}

export default function TripView({ group, user, profile, request, onUpdated, onRefresh, onEditProfile }) {
  const navigate = useNavigate();
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

  // Refresh when the person comes back to the tab or app, and every so often while it's on screen.
  const refreshRef = useRef(onRefresh);
  refreshRef.current = onRefresh;
  const leaveRef = useRef(null);
  useEffect(() => {
    const quietly = () => {
      if (document.visibilityState !== 'visible') return;
      refreshRef.current().catch((error) => { if (error.status === 404) leaveRef.current('This trip was deleted, or you’re no longer on it.'); });
    };
    const timer = setInterval(quietly, POLL_MS);
    document.addEventListener('visibilitychange', quietly);
    window.addEventListener('focus', quietly);
    return () => { clearInterval(timer); document.removeEventListener('visibilitychange', quietly); window.removeEventListener('focus', quietly); };
  }, []);

  // The just-added expense gets a brief "sticker slapped on" highlight.
  const [fresh, setFresh] = useState(null);
  useEffect(() => {
    if (!fresh) return undefined;
    const timer = setTimeout(() => setFresh(null), 1600);
    return () => clearTimeout(timer);
  }, [fresh]);
  useEffect(() => {
    if (!notice) return undefined;
    const timer = setTimeout(() => setNotice(null), notice.undo ? 10000 : 5000);
    return () => clearTimeout(timer);
  }, [notice]);
  // NITEHARTS trip pages wear its heart as the tab and home-screen icon.
  const niteharts = isNiteharts(group);
  useEffect(() => {
    if (!niteharts) return undefined;
    const links = [['icon', 'favicon.svg', 'image/svg+xml'], ['icon', 'favicon-32.png', 'image/png'], ['apple-touch-icon', 'apple-touch-icon.png']].map(([rel, file, type]) => {
      const link = Object.assign(document.createElement('link'), { rel, href: `/trips/niteharts/${file}` });
      if (type) link.type = type;
      return document.head.appendChild(link);
    });
    return () => links.forEach((link) => link.remove());
  }, [niteharts]);
  const me = myMember(group, user.id);
  const owner = group.owner_id === user.id;
  const admin = Boolean(profile?.is_admin);
  const setTab = (key) => setParams((next) => { next.set('tab', key); return next; }, { replace: true });
  const close = () => setModal(null);
  // Sub-steps (delete, edit, rename…) go back to the sheet they came from.
  const back = () => setModalState(modal?.back || null);

  // Edits and deletes are compare-and-swap. On conflict: load the latest trip, keep the open draft, and require an
  // explicit second save against the newly shown version. New records don't conflict; the server adds them on top.
  const update = async (path, method, payload, message, undo, { keepModal = false } = {}) => {
    let result;
    try {
      result = await request(`/groups/${group.id}${path}`, method, payload);
    } catch (error) {
      if (error.status === 409 && alive.current) {
        const fresh = await onRefresh().catch(() => null);
        if (keepModal) throw new Error('Someone changed this trip first. The latest version is loaded; try again.');
        if (fresh && alive.current) setModalState((current) => current && { ...current, revision: fresh.revision, conflict: true });
        throw new Error(CONFLICT);
      }
      throw error;
    }
    if (!alive.current) return result;
    onUpdated(result.group || result);
    setNotice({ message, undo });
    if (!keepModal) setModalState(null);
    return result;
  };
  const formGroup = modal ? { ...group, revision: modal.revision } : group;
  const refresh = async () => {
    setRefreshing(true);
    try { await onRefresh(); setNotice({ message: 'Up to date.' }); } catch (e) { setNotice({ message: e.message }); } finally { if (alive.current) setRefreshing(false); }
  };
  const recordPayment = (payload) => update('/repayments', 'POST', payload,
    `Recorded ${memberName(findMember(group, payload.from_member))} → ${memberName(findMember(group, payload.to_member))}, ${money(payload.amount_minor, group.currency)}.`,
    () => update(`/repayments/${payload.id}`, 'DELETE', { revision: latest.current.revision }, 'Payment removed.', null, { keepModal: true }));
  const obligationAction = async (obligation, action) => {
    try {
      return await update(`/obligations/${obligation.id}/${action}`, 'POST', { cycle: obligation.cycle || 0 },
        action === 'settle' ? 'Payment settled.' : action === 'undo' ? 'Payment reopened.' : 'Nudge sent.',
        action === 'settle' ? () => obligationAction(obligation, 'undo') : null, { keepModal: action === 'undo' });
    } catch (error) { setNotice({ message: error.message }); throw error; }
  };
  const restore = (expense, options) => update(`/expenses/${expense.id}/restore`, 'POST', { revision: latest.current.revision }, `Restored ${expense.description}.`, null, options);
  // Adding a missing Venmo username from the pay dialog keeps the dialog open.
  const saveHandle = async (member, username) => {
    const result = await request(`/groups/${group.id}/members/${member.id}/venmo`, 'PUT', { venmo_username: username, revision: latest.current.revision });
    if (alive.current) onUpdated(result);
  };
  const leave = (notice) => { if (alive.current) navigate('/trips', { state: { notice } }); };
  leaveRef.current = leave;
  const deleteTrip = async () => {
    try {
      await request(`/groups/${group.id}`, 'DELETE', { revision: modal.revision });
    } catch (error) {
      if (error.status === 404) return leave(`Deleted ${group.name}.`); // A retry after a lost response.
      if (error.status === 409 && alive.current) {
        const fresh = await onRefresh().catch(() => null);
        if (fresh && alive.current) setModalState((current) => current && { ...current, revision: fresh.revision });
        throw new Error('Someone changed this trip. Check the latest totals, then delete again.');
      }
      throw error;
    }
    return leave(`Deleted ${group.name}.`);
  };
  const addPeople = async (names) => {
    // Sequential adds; a retry after a partial failure skips people who were already added.
    const existing = new Set(latest.current.members.map((m) => m.name.toLowerCase()));
    const fresh = names.filter((name) => !existing.has(name.toLowerCase()));
    if (!fresh.length) throw new Error('Everyone listed is already on this trip.');
    const links = addedLinks.current; // Survives a failed attempt, so earlier invite links aren't lost.
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
    setNotice({ message: `Added ${links.map((l) => l.name).join(', ')}.` });
    addedLinks.current = [];
    setModal({ type: 'invites', links });
  };
  const addedLinks = useRef([]);
  const modalName = modal?.member ? memberName(modal.member) : '';
  const titles = { expense: modal?.expense ? 'Edit expense' : 'Add expense', expense_detail: modal?.item?.description, repayment: 'Record a payment',
    venmo: modal?.role === 'request' ? 'Request with Venmo' : 'Pay with Venmo', people: 'Add people', invites: 'Invite links', invite: `Invite ${modalName}`,
    member_venmo: `Venmo for ${modalName}`, person: modalName, rename_member: `Rename ${modalName}`, remove_member: `Remove ${modalName}?`,
    link_accounts: 'Link people to accounts', unlink_member: `Unlink ${modalName}?`, trip_settings: 'Trip settings', delete_trip: 'Delete this trip?', delete_expense: 'Delete this expense?', delete_repayment: 'Remove this payment?' };
  const myBalance = group.balances[me?.id] || 0;
  const hasHistory = group.expenses.length + group.repayments.length > 0;
  const openExpense = (expense) => setModal({ type: 'expense_detail', item: expense });
  const ownerName = memberName(group.members.find((m) => m.user_id === group.owner_id));
  const showInvite = (name, token) => setModal({ type: 'invites', links: [{ name, link: `${window.location.origin}/trips/join/${group.id}#invite=${token}` }] });
  const person = (type) => () => setModalState({ type, member: modal.member, revision: latest.current.revision, back: modal });

  return <div className={`trips-trip trips-trip--${tab}`}>
    <div className="trips-breadcrumb"><Link to="/trips"><ArrowLeft size={15} aria-hidden="true" />Trips</Link>
      <button aria-label="Refresh trip" disabled={refreshing} onClick={refresh}><RefreshCw size={14} className={refreshing ? 'trips-refreshing' : ''} aria-hidden="true" />{refreshing ? 'Refreshing…' : 'Refresh'}</button></div>
    <section className="trips-heading">
      <div className="trips-trip-title"><TripStamp trip={group} size={52} /><div><h1 tabIndex={-1}>{group.name}</h1>
        <p className="trips-trip-meta"><AvatarStack members={group.members} />{group.members.length} {group.members.length === 1 ? 'person' : 'people'} · {money(group.total_minor, group.currency)} total</p></div></div>
      <div className="trips-heading-actions">
        {me && tab !== 'balances' && <button className={`trips-balance-pill trips-balance-pill--${myBalance < 0 ? 'owe' : myBalance > 0 ? 'owed' : 'even'}`} onClick={() => setTab('balances')}>
          {myBalance < 0 ? `You owe ${money(-myBalance, group.currency)}` : myBalance > 0 ? `You’re owed ${money(myBalance, group.currency)}` : 'All square'}</button>}
        <Button variant="primary" className="trips-add" onClick={() => setModal({ type: 'expense' })}><Plus size={18} aria-hidden="true" /><span>Add expense</span></Button>
      </div>
    </section>
    <div role="status" aria-live="polite" className="trips-notice">{notice && <>{notice.message}{notice.undo && <button className="trips-text-button" onClick={async () => {
      const undo = notice.undo; setNotice(null);
      try { await undo(); } catch (e) { setNotice({ message: e.message }); }
    }}>Undo</button>}</>}</div>

    {group.obligations?.filter(o => o.status === 'open' && o.from_member === me?.id && o.nudged_at).map(o => <p className="trips-nudge-banner" role="status" key={o.id}>{memberName(findMember(group, o.to_member))} nudged you about {money(o.amount_minor, group.currency)}.</p>)}
    <nav className="trips-tabs" role="tablist" aria-label="Trip sections">{tabs.map(({ key, label, icon: Icon }) => <button key={key} role="tab" id={`trips-tab-${key}`} aria-controls="trips-panel" aria-selected={tab === key} onClick={() => setTab(key)}>
      <Icon size={18} aria-hidden="true" /><span>{label}</span>{key === 'expenses' && <span className="trips-count">{group.expenses.length}</span>}</button>)}</nav>

    <div className={`trips-columns trips-columns--${tab}`}>
      <section className="trips-ledger" id="trips-panel" role="tabpanel" aria-labelledby={`trips-tab-${tab}`}>
        {tab === 'expenses' && <>
          <div className="trips-panel-heading"><h2 className="trips-section-heading"><ReceiptText size={16} aria-hidden="true" />Expenses</h2>
            {hasHistory && <label className="trips-search"><Search size={15} aria-hidden="true" /><input type="search" name="search" aria-label="Search expenses" placeholder="Search" value={query} onChange={(e) => setQuery(e.target.value)} /></label>}</div>
          <Feed group={group} me={me} query={query} fresh={fresh} onOpenExpense={openExpense} onOpenPayment={(item) => setModal({ type: 'delete_repayment', item })} />
        </>}
        {tab === 'balances' && <BalancesPanel request={request} group={group} me={me} profile={profile} onEditProfile={onEditProfile}
          onVenmo={(transfer, role) => setModal({ type: 'venmo', transfer, role })}
          onSettle={o => obligationAction(o, 'settle')} onUndo={o => obligationAction(o, 'undo').catch(() => {})} onNudge={o => obligationAction(o, 'nudge').catch(() => {})}
          onRecord={(suggestion) => setModal({ type: 'repayment', suggestion })}
          onRemoveRepayment={(item) => setModal({ type: 'delete_repayment', item })} />}
        {tab === 'people' && <PeoplePanel group={group} user={user} onEditProfile={onEditProfile} onAdd={() => { addedLinks.current = []; setModal({ type: 'people' }); }}
          onManage={(member) => setModal({ type: 'person', member })} onSettings={() => setModal({ type: 'trip_settings' })}
          onLinkAccounts={admin ? () => setModal({ type: 'link_accounts' }) : null} />}
        {tab === 'activity' && <>
          <div className="trips-panel-heading"><h2 className="trips-section-heading"><History size={16} aria-hidden="true" />Activity</h2></div>
          <ActivityList group={group} me={me} onOpenExpense={openExpense} onRestore={(expense) => restore(expense).catch((e) => setNotice({ message: e.message }))} />
        </>}
      </section>
      <aside className="trips-balance-card" aria-label="Member balances"><h2 className="trips-section-heading"><HandCoins size={16} aria-hidden="true" />Balances</h2>
        {group.members.map((m) => { const balance = group.balances[m.id] || 0; return <div className="trips-balance-row" key={m.id}><Avatar member={m} size={28} /><span>{memberName(m)}</span>
          <strong className={balance > 0 ? 'trips-positive' : balance < 0 ? 'trips-owe' : ''}><small>{balance < 0 ? 'owes' : balance > 0 ? 'gets back' : 'square'}</small>{balance !== 0 && money(Math.abs(balance), group.currency)}</strong></div>; })}
      </aside>
    </div>

    {modal && <Modal key={modal.type} title={titles[modal.type]} onClose={close}>
      {modal.type === 'expense_detail' && (() => {
        const current = group.expenses.find((e) => e.id === modal.item.id);
        if (!current) return <p className="trips-note" role="status">Someone deleted this expense.</p>;
        return <ExpenseDetail group={group} expense={current} meId={me?.id} onClose={close}
          onEdit={() => setModalState({ type: 'expense', expense: current, revision: latest.current.revision, back: { ...modal, item: current } })}
          onDelete={() => setModalState({ type: 'delete_expense', item: current, revision: latest.current.revision, back: modal })} />;
      })()}
      {modal.type === 'expense' && <ExpenseForm group={formGroup} user={user} expense={modal.expense} initial={modal.initial} conflict={modal.conflict && modal.expense ? { latest: group.expenses.find((e) => e.id === modal.expense.id) || null } : null}
        onCancel={back}
        onDelete={() => setModalState({ type: 'delete_expense', item: modal.expense, revision: modal.revision, back: modal })}
        onSave={async (payload) => {
          await update(`/expenses${modal.expense ? `/${modal.expense.id}` : ''}`, modal.expense ? 'PUT' : 'POST', payload, modal.expense ? 'Expense updated.' : `Added ${payload.description}.`);
          if (!modal.expense && alive.current) setFresh(payload.id);
        }} />}
      {modal.type === 'repayment' && <RepaymentForm group={formGroup} meId={me?.id} suggestion={modal.suggestion} onCancel={close} onSave={recordPayment} />}
      {modal.type === 'venmo' && <VenmoReview key={`${modal.transfer.from_member}-${modal.transfer.to_member}`} request={request}
        obligation={group.obligations?.find(o => o.status === 'open' && o.from_member === modal.transfer.from_member && o.to_member === modal.transfer.to_member && o.amount_minor === modal.transfer.amount_minor)}
        onSettle={o => obligationAction(o, 'settle')} group={formGroup} transfer={modal.transfer} role={modal.role} onCancel={close} onRecord={recordPayment}
        onSaveHandle={owner ? (username) => saveHandle(findMember(group, modal.role === 'pay' ? modal.transfer.to_member : modal.transfer.from_member), username) : null} />}
      {modal.type === 'people' && <AddPeopleForm onCancel={close} onSave={addPeople} />}
      {modal.type === 'invites' && <InviteLinks links={modal.links} tripName={group.name} inviter={ownerName} onClose={close} />}
      {modal.type === 'person' && <PersonSheet request={request} group={group} member={findMember(group, modal.member.id) || modal.member}
        onInvite={person('invite')} onVenmo={person('member_venmo')} onRename={person('rename_member')} onRemove={person('remove_member')}
        onUnlink={admin ? person('unlink_member') : null} />}
      {modal.type === 'link_accounts' && <LinkAccounts group={group} request={request} onClose={close}
        onLink={(memberId, userId, revision, message) => update(`/members/${memberId}/link`, 'POST', { revision, user_id: userId }, message, null, { keepModal: true })} />}
      {modal.type === 'unlink_member' && <Form destructive submit="Unlink" onCancel={back} onSubmit={async () => {
        // Names the account being removed, so a retry after someone else's correction can't revoke the new one.
        const result = await update(`/members/${modal.member.id}/unlink`, 'POST', { revision: modal.revision, user_id: modal.member.user_id }, `Unlinked ${memberName(modal.member)}.`);
        if (alive.current) showInvite(memberName(modal.member), result.invite_token);
      }}><p>{memberName(modal.member)}’s account loses access to this trip. Their expenses and payments stay on this place as {modal.member.name}.</p>
        <p className="trips-muted">You’ll get a new invite link so the right person can claim it.</p></Form>}
      {modal.type === 'invite' && <Form submit="Create invite link" onCancel={back} onSubmit={async () => {
        const result = await update(`/members/${modal.member.id}/invite`, 'POST', { revision: modal.revision }, 'Invite link ready.');
        if (alive.current) showInvite(memberName(modal.member), result.invite_token);
      }}><p>A new one-use link for {memberName(modal.member)}. Older links for them stop working.</p></Form>}
      {modal.type === 'member_venmo' && <VenmoForm initial={modal.member.venmo_username} onCancel={back}
        hint={`Only for this trip, until ${firstName(modal.member)} joins and adds their own.`}
        onSave={(username) => update(`/members/${modal.member.id}/venmo`, 'PUT', { venmo_username: username, revision: modal.revision }, username ? `Saved @${username}.` : 'Venmo removed.')} />}
      {modal.type === 'rename_member' && <RenameForm label="Name" initial={modal.member.name} onCancel={back}
        onSave={(name) => update(`/members/${modal.member.id}`, 'PUT', { name, revision: modal.revision }, `Renamed ${modal.member.name} to ${name}.`)} />}
      {modal.type === 'remove_member' && <Form destructive submit="Remove" onCancel={back}
        onSubmit={() => update(`/members/${modal.member.id}`, 'DELETE', { revision: modal.revision }, `Removed ${memberName(modal.member)}.`)}>
        <p>{memberName(modal.member)} isn’t on any expenses or payments, so nobody’s balance changes.</p>
        {modal.member.user_id && <p className="trips-muted">They’ll lose access to this trip.</p>}</Form>}
      {modal.type === 'trip_settings' && <TripSettings group={group} onCancel={close}
        onRename={(name) => update('', 'PUT', { name, revision: modal.revision }, 'Trip renamed.')}
        onDelete={() => setModalState({ type: 'delete_trip', revision: modal.revision, back: modal })} />}
      {modal.type === 'delete_trip' && <Form destructive submit="Delete trip" onCancel={back} onSubmit={deleteTrip}>
        <p>Delete <strong>{group.name}</strong>, its {group.expenses.length} {group.expenses.length === 1 ? 'expense' : 'expenses'} and {group.repayments.length} {group.repayments.length === 1 ? 'payment' : 'payments'}?</p>
        <p className="trips-muted">It’s removed for everyone on the trip. This can’t be undone.</p></Form>}
      {modal.type === 'delete_expense' && <Form destructive submit="Delete expense" onCancel={back} onSubmit={() => {
        const item = modal.item;
        return update(`/expenses/${item.id}`, 'DELETE', { revision: modal.revision }, `Deleted ${item.description}.`, () => restore(item, { keepModal: true }));
      }}>
        {modal.conflict ? (() => {
          const current = group.expenses.find((e) => e.id === modal.item.id);
          return current ? <div className="trips-note" role="status"><strong>Someone changed this expense. Delete this version?</strong>
            <ul className="trips-conflict">{savedSummary(current, group).map((line) => <li key={line}>{line}</li>)}</ul></div>
            : <p className="trips-note" role="status">Someone already deleted this expense.</p>;
        })() : <p>{modal.item.description} · {money(modal.item.amount_minor, group.currency)}</p>}
        <p className="trips-muted">Everyone’s balance will update. You can undo this.</p></Form>}
      {modal.type === 'delete_repayment' && <Form destructive submit="Remove payment" onCancel={close} onSubmit={() => update(`/repayments/${modal.item.id}`, 'DELETE', { revision: modal.revision }, 'Payment removed.')}>
        <p>{memberName(findMember(group, modal.item.from_member))} paid {memberName(findMember(group, modal.item.to_member))} · {money(modal.item.amount_minor, group.currency)} · {shortDate(modal.item.date)}{modal.item.notes ? ` · ${modal.item.notes}` : ''}</p>
        <p className="trips-muted">Remove it only if it didn’t happen or was recorded twice. Balances go back to before it.</p></Form>}
    </Modal>}
  </div>;
}
