import VenmoProfile from './VenmoProfile.jsx';
import React, { useEffect, useRef, useState } from 'react';
import { ArrowRight, Check, ExternalLink, HandCoins, Plus, Trash2 } from 'lucide-react';
import { decimal, money, shortDate, today, toMinor } from './money.js';
import { Avatar, Button, CopyButton, Field, Form, VenmoMark } from './ui.jsx';
import { findMember, firstName, memberName } from './people.js';
import { normalizeUsername, settlementRole, tripNote, venmoLink, venmoProfile } from './venmo.js';
import { balanceBreakdown } from './balances.js';

const SquareStamp = () => <span className="trips-square-stamp" aria-hidden="true">All square</span>;


// A return confirmation belongs to the payment actually opened, never a refreshed suggestion.
function useVenmoReturn(obligation, handle) {
  const [opened, setOpened] = useState(null);
  const [returned, setReturned] = useState(false);
  const [invalid, setInvalid] = useState(false);
  const matches = Boolean(opened && obligation?.status === 'open' && opened.obligation.id === obligation.id
    && (opened.obligation.cycle || 0) === (obligation.cycle || 0)
    && opened.obligation.amount_minor === obligation.amount_minor && opened.handle === handle);
  useEffect(() => { if (opened && !matches) setInvalid(true); }, [opened, matches]);
  useEffect(() => {
    if (!matches || invalid) return;
    const returning = () => { if (document.visibilityState !== 'hidden') setReturned(true); };
    window.addEventListener('focus', returning);
    document.addEventListener('visibilitychange', returning);
    return () => { window.removeEventListener('focus', returning); document.removeEventListener('visibilitychange', returning); };
  }, [matches, invalid]);
  return {
    opened, pending: matches && !invalid ? opened : null, returned: returned && matches && !invalid,
    open: () => { if (obligation) { setOpened({ obligation: { ...obligation }, handle }); setReturned(false); setInvalid(false); } },
    dismiss: () => { setOpened(null); setReturned(false); setInvalid(false); },
  };
}

export function RepaymentForm({ group, meId, suggestion, onSave, onCancel }) {
  const [id] = useState(() => crypto.randomUUID());
  // Without a suggestion, start from your own suggested payment, else from you to the next person.
  const start = suggestion || group.transfers.find((t) => settlementRole(t, meId))
    || { from_member: meId || group.members[0].id, to_member: group.members.find((m) => m.id !== (meId || group.members[0].id))?.id };
  const [from, setFrom] = useState(start.from_member);
  const [to, setTo] = useState(start.to_member || group.members[0].id);
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
// `onSaveHandle` lets the trip creator add a missing username right here, for someone who hasn't joined.
export function VenmoReview({ group, transfer, role, onRecord, onCancel, onSaveHandle, request, obligation, onSettle }) {
  const [id] = useState(() => crypto.randomUUID());
  const other = findMember(group, role === 'pay' ? transfer.to_member : transfer.from_member);
  const username = other?.venmo_username;
  const payment = obligation || (!group.obligations ? { id, cycle: 0, amount_minor: transfer.amount_minor, status: 'open' } : null);
  const { pending, returned, opened, open, dismiss } = useVenmoReturn(payment, username);
  const note = [tripNote(group.name), obligation?.reference].filter(Boolean).join(' · ');
  const settle = () => {
    if ((opened && !pending) || (group.obligations && !obligation)) throw new Error('This payment changed. Close and review the latest amounts.');
    return obligation && onSettle ? onSettle(pending?.obligation || obligation) : onRecord({ id, from_member: transfer.from_member, to_member: transfer.to_member, amount_minor: transfer.amount_minor, date: today(), notes: 'Venmo', revision: group.revision });
  };
  const amount = decimal(transfer.amount_minor);
  const usd = group.currency === 'USD';
  const canAddHandle = usd && !username && onSaveHandle && !other?.user_id;
  return <Form name="venmo" submit={role === 'pay' ? 'Sent' : 'Got it'} submitVariant="primary"
    onCancel={onCancel} onSubmit={settle}>
    <div className="trips-venmo-who">{!username && <Avatar member={other} size={44} />}<div>
      <strong>{role === 'pay' ? `Pay ${memberName(other)}` : `Request from ${memberName(other)}`}</strong>
      {!username && <span className="trips-muted">No Venmo username yet</span>}
    </div></div>
    <VenmoProfile handle={username} request={request} confirmedName={other?.venmo_confirmed_name} />
    <strong className="trips-venmo-amount">{money(transfer.amount_minor, group.currency)}</strong>
    {usd && username && <a className="cc-button cc-button--primary trips-venmo-open" href={venmoLink({ username, role, amountMinor: transfer.amount_minor, note })}
      target="_blank" rel="noopener noreferrer" onClick={open}><VenmoMark />{role === 'pay' ? `Pay @${username} ${money(transfer.amount_minor, group.currency)}` : `Request ${money(transfer.amount_minor, group.currency)} from @${username}`} <ExternalLink size={14} aria-hidden="true" /></a>}
    {canAddHandle && <InlineHandle name={firstName(other)} onSave={onSaveHandle} />}
    {usd && !username && !canAddHandle && <p className="trips-muted">{firstName(other)} hasn’t added a Venmo username. {other?.user_id ? `Ask ${firstName(other)} to add it in their profile, or` : 'Ask the trip creator to add it, or'} pay with the details below.</p>}
    {!usd && <p className="trips-muted">Venmo only sends US dollars. Use the details below with another app.</p>}
    <dl className="trips-venmo-details">
      {username && <div><dt>To</dt><dd>@{username}</dd><CopyButton value={username} label="Venmo username" /></div>}
      <div><dt>Amount</dt><dd>{money(transfer.amount_minor, group.currency)}</dd><CopyButton value={amount} label="amount" /></div>
      <div><dt>Note</dt><dd>{note}</dd><CopyButton value={note} label="note" /></div>
    </dl>
    {returned && <div className="trips-return-prompt" role="status">
      <strong>{role === 'pay' ? `Did you send ${money(transfer.amount_minor, group.currency)} to @${username}?` : `Did ${money(transfer.amount_minor, group.currency)} from @${username} come in?`}</strong>
      <Button type="button" variant="ghost" onClick={dismiss}>Not yet</Button>
      <Button type="button" variant="ghost" aria-label="Dismiss payment prompt" onClick={dismiss}>Dismiss</Button>
    </div>}
    {username && <a href={venmoProfile(username)} target="_blank" rel="noopener noreferrer">Check in Venmo</a>}
  </Form>;
}

// Not a nested form: the dialog's own form owns submit, so this saves on its own button.
function InlineHandle({ name, onSave }) {
  const [value, setValue] = useState('');
  const [state, setState] = useState({ busy: false, error: '' });
  const save = async () => {
    setState({ busy: true, error: '' });
    try {
      const username = normalizeUsername(value);
      if (!username) throw new Error(`Enter ${name}’s Venmo username.`);
      await onSave(username);
    } catch (error) { setState({ busy: false, error: error.message }); return; }
    setState({ busy: false, error: '' });
  };
  return <div className="trips-inline-handle">
    <label htmlFor="trips-inline-handle">{name}’s Venmo username</label>
    <div><input id="trips-inline-handle" autoCapitalize="none" autoCorrect="off" spellCheck={false} autoComplete="off" placeholder="@username"
      value={value} disabled={state.busy} onChange={(e) => setValue(e.target.value)}
      onKeyDown={(e) => { if (e.key === 'Enter') { e.preventDefault(); save(); } }} />
      <Button type="button" disabled={state.busy} onClick={save}>{state.busy ? 'Saving…' : 'Add'}</Button></div>
    <small>Only for this trip, until {name} joins and adds their own.</small>
    {state.error && <p className="trips-error" role="alert">{state.error}</p>}
  </div>;
}

function TransferRow({ group, transfer, meId, onVenmo, onRecord, onSettle, onNudge, request }) {
  const obligation = group.obligations?.find(o => o.status === 'open' && o.from_member === transfer.from_member && o.to_member === transfer.to_member && o.amount_minor === transfer.amount_minor);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const role = settlementRole(transfer, meId);
  const from = findMember(group, transfer.from_member);
  const to = findMember(group, transfer.to_member);
  const other = role === 'request' ? from : to;
  const { pending, returned: prompt, open, dismiss } = useVenmoReturn(obligation, other?.venmo_username);
  const settle = async (payment) => {
    if (busy) return;
    setBusy(true); setError('');
    try { await onSettle(payment); dismiss(); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const label = (m) => (m?.id === meId ? 'You' : memberName(m));
  return <li className={`trips-transfer${role ? ' trips-transfer--mine' : ''}`}>
    <span className="trips-transfer-people"><Avatar member={from} size={30} /><ArrowRight size={14} aria-hidden="true" /><Avatar member={to} size={30} />
      <span><strong>{label(from)}</strong> {role === 'pay' ? 'pay' : 'pays'} <strong>{to?.id === meId ? 'you' : memberName(to)}</strong></span></span>
    {role === 'request' && other?.venmo_username && <VenmoProfile handle={other.venmo_username} request={request} confirmedName={other.venmo_confirmed_name} />}
    <strong className="trips-transfer-amount">{money(transfer.amount_minor, group.currency)}</strong>
    <span className="trips-transfer-actions">
      {role === 'request' && group.currency === 'USD' && other?.venmo_username && obligation
        ? <a className="cc-button cc-button--secondary" href={venmoLink({ username: other.venmo_username, role, amountMinor: transfer.amount_minor, note: tripNote(group.name), reference: obligation.reference })}
          target="_blank" rel="noopener noreferrer" onClick={open} aria-label={`Request ${money(transfer.amount_minor, group.currency)} from @${other.venmo_username}`}><VenmoMark />Request</a>
        : role && group.currency === 'USD' && <Button variant={role === 'pay' ? 'primary' : 'secondary'} onClick={() => onVenmo(transfer, role)}
          aria-label={`${role === 'pay' ? 'Pay' : 'Request from'} ${memberName(role === 'pay' ? to : from)} with Venmo`}><VenmoMark />{role === 'pay' ? 'Pay' : 'Request'}</Button>}
      <Button variant="ghost" disabled={busy} onClick={() => obligation && role && onSettle ? settle(obligation) : onRecord(transfer)} aria-label={`Record payment from ${memberName(from)} to ${memberName(to)}`}><Check size={15} aria-hidden="true" />{role === 'request' ? 'Received' : role === 'pay' ? 'Paid' : 'Record'}</Button>
      {role && (role === 'pay' ? to : from)?.venmo_username && <a href={venmoProfile((role === 'pay' ? to : from).venmo_username)} target="_blank" rel="noopener noreferrer">Check in Venmo</a>}
      {prompt && <div className="trips-return-prompt" role="status"><strong>Did {money(pending?.obligation.amount_minor, group.currency)} from @{pending?.handle} come in?</strong><Button disabled={busy} onClick={() => pending && settle(pending.obligation)}>Got it</Button><Button variant="ghost" onClick={dismiss}>Not yet</Button><Button variant="ghost" aria-label="Dismiss payment prompt" onClick={dismiss}>Dismiss</Button><a href={venmoProfile(other?.venmo_username)} target="_blank" rel="noopener noreferrer">Check in Venmo</a></div>}
      {error && <p role="alert">{error}</p>}
      {role === 'request' && obligation && Date.now() - Date.parse(obligation.created_at) >= 3 * 86400000 && (!obligation.nudged_at || Date.now() - Date.parse(obligation.nudged_at) >= 48 * 3600000) && <Button variant="ghost" onClick={() => onNudge?.(obligation)}>Nudge</Button>}
    </span>
  </li>;
}

export function BalancesPanel({ group, me, profile, onVenmo, onRecord, onRemoveRepayment, onEditProfile, onSettle, onUndo, onNudge, request }) {
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
  // Pairwise debts differ from the plan once payments are simplified; say so instead of contradicting it.
  const planned = Object.fromEntries(group.transfers.filter((t) => settlementRole(t, me?.id))
    .map((t) => (t.from_member === me.id ? [t.to_member, t.amount_minor] : [t.from_member, -t.amount_minor])));
  const simplified = Boolean(breakdown) && (breakdown.direct.length !== Object.keys(planned).length
    || breakdown.direct.some((row) => planned[row.member_id] !== row.amount_minor));
  const mine = group.transfers.filter((t) => settlementRole(t, me?.id)).sort((a, b) => Number(b.to_member === me?.id) - Number(a.to_member === me?.id));
  const others = group.transfers.filter((t) => !settlementRole(t, me?.id));
  const owedWithoutHandle = myBalance > 0 && group.currency === 'USD' && profile && !profile.venmo_username;
  return <>
    {me && <section className={`trips-hero trips-hero--${myBalance < 0 ? 'owe' : myBalance > 0 ? 'owed' : 'even'}${celebrate ? ' trips-hero--celebrate' : ''}`} aria-label="Your balance">
      <span>{myBalance < 0 ? 'You owe' : myBalance > 0 ? 'You’re owed' : 'You’re all square'}</span>
      {myBalance !== 0 ? <strong>{money(Math.abs(myBalance), group.currency)}</strong> : <SquareStamp />}
      {owedWithoutHandle && <button type="button" className="trips-text-button" onClick={onEditProfile}><VenmoMark />Add your Venmo to get paid</button>}
    </section>}

    <div className="trips-panel-heading"><h2 className="trips-section-heading"><HandCoins size={16} aria-hidden="true" />Settle up</h2></div>
    {!!group.transfers.length && <p className="trips-muted trips-small trips-settle-note">{group.settlement === 'fewest'
      ? 'The fewest payments to square everyone.'
      : 'These square everyone with the least money changing hands.'}</p>}
    {!group.transfers.length ? <div className="trips-empty trips-empty--square">{!me && <SquareStamp />}<p>All square. Nobody owes anybody.</p></div> : <>
      {!!mine.some(t => t.to_member === me?.id) && <h3 className="trips-subheading">Who owes you</h3>}
      {!!mine.length && <ul className="trips-transfers">{mine.map((t) => <TransferRow key={`${t.from_member}-${t.to_member}`} group={group} transfer={t} meId={me?.id} onVenmo={onVenmo} onRecord={onRecord} onSettle={onSettle} onNudge={onNudge} request={request} />)}</ul>}
      {!!others.length && <>{!!mine.length && <h3 className="trips-subheading">Between others</h3>}
        <ul className="trips-transfers">{others.map((t) => <TransferRow key={`${t.from_member}-${t.to_member}`} group={group} transfer={t} meId={me?.id} onVenmo={onVenmo} onRecord={onRecord} onSettle={onSettle} onNudge={onNudge} request={request} />)}</ul></>}
    </>}

    {breakdown && <details className="trips-calculation"><summary>How your balance adds up</summary>
      <dl className="trips-calculation-totals"><div><dt>You paid</dt><dd>{money(breakdown.paid, group.currency)}</dd></div><div><dt>Your share</dt><dd>−{money(breakdown.share, group.currency)}</dd></div>
        {!!breakdown.sent && <div><dt>Payments you sent</dt><dd>{money(breakdown.sent, group.currency)}</dd></div>}{!!breakdown.received && <div><dt>Payments you received</dt><dd>−{money(breakdown.received, group.currency)}</dd></div>}
        <div><dt>{breakdown.net < 0 ? 'You owe' : breakdown.net > 0 ? 'You’re owed' : 'Balance'}</dt><dd>{money(Math.abs(breakdown.net), group.currency)}</dd></div></dl>
      <h3>{simplified ? 'Before simplifying' : 'Person by person'}</h3>
      {simplified && <p className="trips-muted trips-small" role="note">{myBalance === 0
        ? 'You’re square: the payments above already cover all of these, so don’t pay any of them.'
        : 'Who covered whom, one person at a time. The payments above replace these, so don’t pay both.'}</p>}
      {!breakdown.direct.length ? <p className="trips-muted">You’re square with everyone.</p> : <ul className="trips-direct-balances">{breakdown.direct.map((row) => {
        const other = findMember(group, row.member_id);
        return <li key={row.member_id}><span><Avatar member={other} size={22} />{memberName(other)}</span><strong className={row.amount_minor > 0 ? 'trips-owe' : 'trips-positive'}>{row.amount_minor > 0 ? 'You owe' : 'Owes you'} {money(Math.abs(row.amount_minor), group.currency)}</strong></li>;
      })}</ul>}
    </details>}

    <h3 className="trips-subheading">Recorded payments</h3>
    {group.members.length > 1 && <Button variant="ghost" className="trips-record-other" onClick={() => onRecord(null)}><Plus size={15} aria-hidden="true" />Record a payment</Button>}
    {!group.repayments.length ? <p className="trips-muted">No payments yet.</p> : <ul className="trips-repayments">{group.repayments.slice().reverse().map((p) => {
      const from = findMember(group, p.from_member);
      const to = findMember(group, p.to_member);
      const settled = group.obligations?.find(o => o.id === p.id && o.status === 'settled');
      return <li key={p.id}><Avatar member={from} size={26} /><div><strong>{memberName(from)} → {memberName(to)}</strong><small>{shortDate(p.date)}{settled ? ` · Settled by ${memberName(findMember(group, settled.settled_by))}` : p.notes && ` · ${p.notes}`}</small></div>
        <strong>{money(p.amount_minor, group.currency)}</strong>
        <button className="trips-text-button" aria-label={`${settled ? 'Undo' : 'Remove'} payment from ${memberName(from)} to ${memberName(to)}, ${money(p.amount_minor, group.currency)} on ${p.date}`} onClick={() => group.obligations?.some(o => o.id === p.id && o.status === 'settled') && onUndo ? onUndo(group.obligations.find(o => o.id === p.id)) : onRemoveRepayment(p)}><Trash2 size={14} aria-hidden="true" />{group.obligations?.some(o => o.id === p.id && o.status === 'settled') ? 'Undo' : 'Remove'}</button></li>;
    })}</ul>}
  </>;
}
