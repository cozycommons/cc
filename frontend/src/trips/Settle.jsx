import React, { useEffect, useRef, useState } from 'react';
import { ArrowRight, Check, ExternalLink, HandCoins, Plus, Undo2 } from 'lucide-react';
import { decimal, money, shortDate, today, toMinor } from './money.js';
import { Avatar, Button, CopyButton, Field, Form } from './ui.jsx';
import { findMember, firstName, memberName } from './people.js';
import { settlementRole, tripNote, venmoLink } from './venmo.js';
import { balanceBreakdown } from './balances.js';

const SquareStamp = () => <span className="trips-square-stamp" aria-hidden="true">All square</span>;

const VenmoMark = () => <span className="trips-venmo-mark" aria-hidden="true">V</span>;

export function RepaymentForm({ group, suggestion, onSave, onCancel }) {
  const [id] = useState(() => crypto.randomUUID());
  const [from, setFrom] = useState(suggestion?.from_member || group.members[0].id);
  const [to, setTo] = useState(suggestion?.to_member || group.members[1]?.id || group.members[0].id);
  const [amount, setAmount] = useState(suggestion ? decimal(suggestion.amount_minor) : '');
  const [date, setDate] = useState(today());
  const [notes, setNotes] = useState(suggestion?.notes || '');
  const options = group.members.map((m) => <option value={m.id} key={m.id}>{memberName(m)}</option>);
  return <Form name="repayment" submit="Record payment" onCancel={onCancel} onSubmit={() => {
    if (from === to) throw new Error('Choose two different people.');
    return onSave({ id, from_member: from, to_member: to, amount_minor: toMinor(amount, false, group.currency), date, notes, revision: group.revision });
  }}>
    <div className="trips-form-grid"><Field label="Who paid"><select name="from_member" value={from} onChange={(e) => setFrom(e.target.value)}>{options}</select></Field>
      <Field label="Who received it"><select name="to_member" value={to} onChange={(e) => setTo(e.target.value)}>{options}</select></Field></div>
    <div className="trips-form-grid"><Field label={`Amount (${group.currency})`}><input name="amount" autoFocus inputMode="decimal" required placeholder="0.00" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
      <Field label="Date"><input name="date" required type="date" value={date} onChange={(e) => setDate(e.target.value)} /></Field></div>
    <Field label="Note (optional)"><input name="notes" maxLength={1000} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Venmo, cash…" /></Field>
  </Form>;
}

// Review before leaving: Venmo shows the same details again, and nothing is recorded until the person says so.
export function VenmoReview({ group, transfer, role, onRecord, onCancel, onEditHandles }) {
  const [id] = useState(() => crypto.randomUUID());
  const [opened, setOpened] = useState(false);
  const other = findMember(group, role === 'pay' ? transfer.to_member : transfer.from_member);
  const username = other?.venmo_username;
  const note = tripNote(group.name);
  const amount = decimal(transfer.amount_minor);
  const usd = group.currency === 'USD';
  return <Form name="venmo" submit={role === 'pay' ? 'Mark as paid' : 'Mark as received'} onCancel={onCancel} onSubmit={() => onRecord({
    id, from_member: transfer.from_member, to_member: transfer.to_member, amount_minor: transfer.amount_minor,
    date: today(), notes: 'Venmo', revision: group.revision })}>
    <div className="trips-venmo-who"><Avatar member={other} size={44} /><div>
      <strong>{role === 'pay' ? `Pay ${memberName(other)}` : `Request from ${memberName(other)}`}</strong>
      {username ? <span>@{username}</span> : <span className="trips-muted">No Venmo username yet</span>}
    </div><strong className="trips-venmo-amount">{money(transfer.amount_minor, group.currency)}</strong></div>
    {username && !other.venmo_confirmed && <p className="trips-note">{other.venmo_source === 'trip' ? 'Added by the trip creator' : 'Added for them'}, not by {firstName(other)}. Check the name in Venmo.</p>}
    <dl className="trips-venmo-details">
      {username && <div><dt>To</dt><dd>@{username}</dd><CopyButton value={username} label="Venmo username" /></div>}
      <div><dt>Amount</dt><dd>{amount}</dd><CopyButton value={amount} label="amount" /></div>
      <div><dt>Note</dt><dd>{note}</dd><CopyButton value={note} label="note" /></div>
    </dl>
    {!usd ? <p className="trips-muted">Venmo only sends US dollars. Use the details above with another app.</p>
      : username ? <a className="cc-button cc-button--primary trips-venmo-open" href={venmoLink({ username, role, amountMinor: transfer.amount_minor, note })}
        target="_blank" rel="noopener noreferrer" onClick={() => setOpened(true)}><VenmoMark />{role === 'pay' ? 'Open Venmo to pay' : 'Open Venmo to request'}<ExternalLink size={14} aria-hidden="true" /></a>
        : <p className="trips-muted">{firstName(other)} hasn’t added a Venmo username. {onEditHandles && <button type="button" className="trips-text-button trips-inline" onClick={onEditHandles}>Add it</button>}</p>}
    {usd && username && <p className="trips-muted" role="status">{opened
      ? `After ${role === 'pay' ? 'you pay' : `${firstName(other)} pays`} in Venmo, record it here.`
      : 'Venmo opens with these details filled in. Confirm there, then record it here.'}</p>}
  </Form>;
}

function TransferRow({ group, transfer, meId, onVenmo, onRecord }) {
  const role = settlementRole(transfer, meId);
  const from = findMember(group, transfer.from_member);
  const to = findMember(group, transfer.to_member);
  const label = (m) => (m?.id === meId ? 'You' : memberName(m));
  return <li className={`trips-transfer${role ? ' trips-transfer--mine' : ''}`}>
    <span className="trips-transfer-people"><Avatar member={from} size={30} /><ArrowRight size={14} aria-hidden="true" /><Avatar member={to} size={30} />
      <span><strong>{label(from)}</strong> {role === 'pay' ? 'pay' : 'pays'} <strong>{to?.id === meId ? 'you' : memberName(to)}</strong></span></span>
    <strong className="trips-transfer-amount">{money(transfer.amount_minor, group.currency)}</strong>
    <span className="trips-transfer-actions">
      {role && group.currency === 'USD' && <Button variant={role === 'pay' ? 'primary' : 'secondary'} onClick={() => onVenmo(transfer, role)}
        aria-label={`${role === 'pay' ? 'Pay' : 'Request from'} ${memberName(role === 'pay' ? to : from)} with Venmo`}>
        <VenmoMark />{role === 'pay' ? 'Pay' : 'Request'}</Button>}
      <Button variant="ghost" onClick={() => onRecord(transfer)} aria-label={`Record payment from ${memberName(from)} to ${memberName(to)}`}><Check size={15} aria-hidden="true" />{role === 'request' ? 'Received' : role === 'pay' ? 'Paid' : 'Record'}</Button>
    </span>
  </li>;
}

export function BalancesPanel({ group, me, profile, onVenmo, onRecord, onRemoveRepayment, onEditProfile }) {
  const myBalance = group.balances[me?.id] || 0;
  // Celebrate only the moment a balance becomes square, never on load.
  const previous = useRef(myBalance);
  const [celebrate, setCelebrate] = useState(false);
  useEffect(() => {
    const becameSquare = previous.current !== 0 && myBalance === 0;
    previous.current = myBalance;
    if (!becameSquare) return undefined;
    setCelebrate(true);
    const timer = setTimeout(() => setCelebrate(false), 1400);
    return () => clearTimeout(timer);
  }, [myBalance]);
  const breakdown = me ? balanceBreakdown(group, me.id) : null;
  const mine = group.transfers.filter((t) => settlementRole(t, me?.id));
  const others = group.transfers.filter((t) => !settlementRole(t, me?.id));
  const owedWithoutHandle = myBalance > 0 && group.currency === 'USD' && profile && !profile.venmo_username;
  return <>
    {me && <section className={`trips-hero trips-hero--${myBalance < 0 ? 'owe' : myBalance > 0 ? 'owed' : 'even'}${celebrate ? ' trips-hero--celebrate' : ''}`} aria-label="Your balance">
      <span>{myBalance < 0 ? 'You owe' : myBalance > 0 ? 'You’re owed' : 'You’re all square'}</span>
      {myBalance !== 0 ? <strong>{money(Math.abs(myBalance), group.currency)}</strong> : <SquareStamp />}
      {owedWithoutHandle && <button type="button" className="trips-text-button" onClick={onEditProfile}><VenmoMark />Add your Venmo to get paid</button>}
    </section>}

    <div className="trips-panel-heading"><h2 className="trips-section-heading"><HandCoins size={16} aria-hidden="true" />Settle up</h2>
      <Button onClick={() => onRecord(null)} disabled={group.members.length < 2}><Plus size={15} aria-hidden="true" />Record payment</Button></div>
    {!group.transfers.length ? <div className="trips-empty trips-empty--square">{!me && <SquareStamp />}<p>All square. Nobody owes anybody.</p></div> : <>
      {!!mine.length && <ul className="trips-transfers">{mine.map((t) => <TransferRow key={`${t.from_member}-${t.to_member}`} group={group} transfer={t} meId={me?.id} onVenmo={onVenmo} onRecord={onRecord} />)}</ul>}
      {!!others.length && <>{!!mine.length && <h3 className="trips-subheading">Between others</h3>}
        <ul className="trips-transfers">{others.map((t) => <TransferRow key={`${t.from_member}-${t.to_member}`} group={group} transfer={t} meId={me?.id} onVenmo={onVenmo} onRecord={onRecord} />)}</ul></>}
      <p className="trips-muted trips-small">{group.settlement === 'fewest'
        ? 'The fewest payments that square everyone up, with the least money changing hands, so you might pay someone other than who covered you.'
        : 'These square everyone up with the least money changing hands, so you might pay someone other than who covered you.'}</p>
    </>}

    {breakdown && <details className="trips-calculation"><summary>How your balance adds up</summary>
      <dl className="trips-calculation-totals"><div><dt>You paid</dt><dd>{money(breakdown.paid, group.currency)}</dd></div><div><dt>Your share</dt><dd>−{money(breakdown.share, group.currency)}</dd></div>
        {!!breakdown.sent && <div><dt>Payments you sent</dt><dd>{money(breakdown.sent, group.currency)}</dd></div>}{!!breakdown.received && <div><dt>Payments you received</dt><dd>−{money(breakdown.received, group.currency)}</dd></div>}
        <div><dt>{breakdown.net < 0 ? 'You owe' : breakdown.net > 0 ? 'You’re owed' : 'Balance'}</dt><dd>{money(Math.abs(breakdown.net), group.currency)}</dd></div></dl>
      <h3>Person by person</h3>
      {!breakdown.direct.length ? <p className="trips-muted">You’re square with everyone.</p> : <ul className="trips-direct-balances">{breakdown.direct.map((row) => {
        const other = findMember(group, row.member_id);
        return <li key={row.member_id}><span><Avatar member={other} size={22} />{memberName(other)}</span><strong className={row.amount_minor > 0 ? 'trips-owe' : 'trips-positive'}>{row.amount_minor > 0 ? 'You owe' : 'Owes you'} {money(Math.abs(row.amount_minor), group.currency)}</strong></li>;
      })}</ul>}
    </details>}

    <h3 className="trips-subheading">Recorded payments</h3>
    {!group.repayments.length ? <p className="trips-muted">No payments yet.</p> : <ul className="trips-repayments">{group.repayments.slice().reverse().map((p) => {
      const from = findMember(group, p.from_member);
      const to = findMember(group, p.to_member);
      return <li key={p.id}><Avatar member={from} size={26} /><div><strong>{memberName(from)} → {memberName(to)}</strong><small>{shortDate(p.date)}{p.notes && ` · ${p.notes}`}</small></div>
        <strong>{money(p.amount_minor, group.currency)}</strong>
        <button className="trips-text-button" aria-label={`Undo payment from ${memberName(from)} to ${memberName(to)}, ${money(p.amount_minor, group.currency)} on ${p.date}`} onClick={() => onRemoveRepayment(p)}><Undo2 size={14} aria-hidden="true" />Undo</button></li>;
    })}</ul>}
  </>;
}
