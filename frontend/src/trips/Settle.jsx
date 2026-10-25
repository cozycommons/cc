import VenmoProfile from './VenmoProfile.jsx';
import React, { useEffect, useRef, useState } from 'react';
import { ArrowRight, Check, ExternalLink, HandCoins, Plus, Trash2 } from 'lucide-react';
import { decimal, money, shortDate, today, toMinor } from './money.js';
import { Avatar, Button, CopyButton, Field, Form } from './ui.jsx';
import { findMember, firstName, memberName } from './people.js';
import { normalizeUsername, settlementRole, tripNote, venmoLink } from './venmo.js';
import { balanceBreakdown } from './balances.js';
import { CheckInVenmo, PaymentPrompt, useVenmoPayment } from './VenmoPayment.jsx';

const SquareStamp = () => <span className="trips-square-stamp" aria-hidden="true">All square</span>;


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
export function VenmoReview({ group, transfer, role, onRecord, onCancel, onSaveHandle, request, obligation, onSettle, paymentFlow }) {
  const [id] = useState(() => crypto.randomUUID());
  const other = findMember(group, role === 'pay' ? transfer.to_member : transfer.from_member);
  const username = other?.venmo_username;
  const payment = obligation || (!group.obligations ? { ...transfer, id, cycle: 0, status: 'open' } : null);
  const localFlow = useVenmoPayment(group);
  const flow = paymentFlow || localFlow;
  const pending = flow.pending;
  const shown = flow.opened && pending ? pending : obligation || transfer;
  const shownAmount = shown.amount_minor;
  const changed = Boolean(group.obligations && !flow.opened && !obligation);
  const opened = flow.opened;
  const note = [tripNote(group.name), pending?.reference || obligation?.reference].filter(Boolean).join(' · ');
  const settle = () => {
    if ((opened && !pending) || changed) throw new Error('This payment changed.');
    return group.obligations && (pending || obligation) && onSettle ? onSettle(pending || obligation) : onRecord({ id, from_member: transfer.from_member, to_member: transfer.to_member, amount_minor: transfer.amount_minor, date: today(), notes: 'Venmo', revision: group.revision });
  };
  const amount = decimal(shownAmount);
  const usd = group.currency === 'USD';
  const canAddHandle = usd && !username && onSaveHandle && !other?.user_id;
  if (changed) return <><p>This payment changed.</p><Button onClick={onCancel}>Close</Button></>;
  return <Form name="venmo" submit={flow.returned ? null : role === 'pay' ? 'Sent' : 'Got it'} submitVariant="primary"
    onCancel={onCancel} onSubmit={settle}>
    {!username && <p className="trips-muted">No Venmo username yet</p>}
    <VenmoProfile handle={username} request={request} confirmedName={other?.venmo_confirmed_name} confirmed={other?.venmo_confirmed} />
    {obligation && group.settle?.started_at && obligation.created_at > group.settle.started_at && <small className="trips-updated">Updated</small>}
    <strong className="trips-venmo-amount">{money(shownAmount, group.currency)}</strong>
    {usd && username && <a className="cc-button cc-button--primary trips-venmo-open" href={venmoLink({ username, role, amountMinor: shownAmount, note })}
      target="_blank" rel="noopener noreferrer" onClick={() => flow.open(pending || payment, role, username)}>{role === 'pay' ? `Pay ${money(shownAmount, group.currency)} in Venmo` : `Request ${money(shownAmount, group.currency)} in Venmo`} <ExternalLink size={14} aria-hidden="true" /></a>}
    {canAddHandle && <InlineHandle name={firstName(other)} onSave={onSaveHandle} />}
    {usd && !username && !canAddHandle && <p className="trips-muted">{firstName(other)} hasn’t added a Venmo username. {other?.user_id ? `Ask ${firstName(other)} to add it in their profile, or` : 'Ask the trip creator to add it, or'} pay with the details below.</p>}
    {!usd && <p className="trips-muted">Venmo only sends US dollars. Use the details below with another app.</p>}
    <dl className="trips-venmo-details">
      {username && <div><dt>To</dt><dd>@{username}</dd><CopyButton value={username} label="Venmo username" /></div>}
      <div><dt>Amount</dt><dd>{money(shownAmount, group.currency)}</dd><CopyButton value={amount} label="amount" /></div>
      <div><dt>Note</dt><dd>{note}</dd><CopyButton value={note} label="note" /></div>
    </dl>
    <PaymentPrompt flow={flow} group={group} onSettle={() => settle()} />
    {username && <CheckInVenmo username={username} />}
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

function TransferRow({ group, transfer, meId, onVenmo, onRecord, onSettle, onNudge, request, paymentFlow }) {
  const obligation = group.obligations?.find(o => o.status === 'open' && o.from_member === transfer.from_member && o.to_member === transfer.to_member);
  const amountMinor = obligation?.amount_minor ?? transfer.amount_minor;
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const role = settlementRole(transfer, meId);
  const from = findMember(group, transfer.from_member);
  const to = findMember(group, transfer.to_member);
  const other = role === 'request' ? from : to;

  const settle = async (payment) => {
    if (busy) return;
    setBusy(true); setError('');
    try { await onSettle(payment); } catch (e) { setError(e.message); } finally { setBusy(false); }
  };
  const label = (m) => (m?.id === meId ? 'You' : memberName(m));
  return <li className={`trips-transfer${role ? ' trips-transfer--mine' : ''}`}>
    {!(role === 'request' && other?.venmo_username) && <span className="trips-transfer-people"><Avatar member={from} size={30} /><ArrowRight size={14} aria-hidden="true" /><Avatar member={to} size={30} />
      <span><strong>{label(from)}</strong> {role === 'pay' ? 'pay' : 'pays'} <strong>{to?.id === meId ? 'you' : memberName(to)}</strong></span></span>}
    {role === 'request' && other?.venmo_username && <VenmoProfile handle={other.venmo_username} request={request} confirmedName={other.venmo_confirmed_name} confirmed={other.venmo_confirmed} />}
    {obligation && group.settle?.started_at && obligation.created_at > group.settle.started_at && <small className="trips-updated">Updated</small>}
    <strong className="trips-transfer-amount">{money(amountMinor, group.currency)}</strong>
    <span className="trips-transfer-actions">
      {role === 'request' && group.currency === 'USD' && other?.venmo_username && obligation
        ? <a className="cc-button cc-button--secondary" href={venmoLink({ username: other.venmo_username, role, amountMinor, note: tripNote(group.name), reference: obligation.reference })}
          target="_blank" rel="noopener noreferrer" onClick={() => paymentFlow.open(obligation, role, other.venmo_username)} aria-label={`Request ${money(amountMinor, group.currency)} from @${other.venmo_username}`}>Request</a>
        : role && group.currency === 'USD' && <Button variant={role === 'pay' ? 'primary' : 'secondary'} onClick={() => onVenmo(transfer, role)}
          aria-label={`${role === 'pay' ? 'Pay' : 'Request from'} ${memberName(role === 'pay' ? to : from)} with Venmo`}>{role === 'pay' ? 'Pay' : 'Request'}</Button>}
      <Button variant="ghost" disabled={busy} onClick={() => obligation && role && onSettle ? settle(obligation) : onRecord(transfer)} aria-label={`Record payment from ${memberName(from)} to ${memberName(to)}`}><Check size={15} aria-hidden="true" />{role === 'request' ? 'Received' : role === 'pay' ? 'Paid' : 'Record'}</Button>
      {role && (role === 'pay' ? to : from)?.venmo_username && <CheckInVenmo username={(role === 'pay' ? to : from).venmo_username} />}
      {error && <p role="alert">{error}</p>}
      {role === 'request' && obligation && Date.now() - Date.parse(obligation.created_at) >= 3 * 86400000 && (!obligation.nudged_at || Date.now() - Date.parse(obligation.nudged_at) >= 48 * 3600000) && <Button variant="ghost" onClick={() => onNudge?.(obligation)}>Nudge</Button>}
    </span>
  </li>;
}

export function BalancesPanel({ group, me, profile, onVenmo, onRecord, onRemoveRepayment, onEditProfile, onSettle, onUndo, onNudge, request, paymentFlow, onReady, onStart, onActivity }) {
  const localFlow = useVenmoPayment(group);
  const flow = paymentFlow || localFlow;
  const started = group.settle?.started !== false;
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
    {!paymentFlow && <PaymentPrompt flow={flow} group={group} onSettle={onSettle} />}
    {me && <section className={`trips-hero trips-hero--${myBalance < 0 ? 'owe' : myBalance > 0 ? 'owed' : 'even'}${celebrate ? ' trips-hero--celebrate' : ''}`} aria-label="Your balance">
      <span>{myBalance < 0 ? started ? 'You owe' : 'You owe so far' : myBalance > 0 ? started ? 'You’re owed' : 'You’re owed so far' : 'You’re all square'}</span>
      {myBalance !== 0 ? <strong>{money(Math.abs(myBalance), group.currency)}</strong> : <SquareStamp />}
      {owedWithoutHandle && <button type="button" className="trips-text-button" onClick={onEditProfile}>Add your Venmo to get paid</button>}
    </section>}

    {!started ? <SettleGate group={group} me={me} onReady={onReady} onStart={onStart} /> : <>
      <ChangedSinceSettling group={group} onActivity={onActivity} />
    <div className="trips-panel-heading"><h2 className="trips-section-heading"><HandCoins size={16} aria-hidden="true" />Settle up</h2></div>
    {!!group.transfers.length && <p className="trips-muted trips-small trips-settle-note">{group.settlement === 'fewest'
      ? 'The fewest payments to square everyone.'
      : 'These square everyone with the least money changing hands.'}</p>}
    {!group.transfers.length ? <div className="trips-empty trips-empty--square">{!me && <SquareStamp />}<p>All square. Nobody owes anybody.</p></div> : <>
      {!!mine.some(t => t.to_member === me?.id) && <h3 className="trips-subheading">Who owes you</h3>}
      {!!mine.length && <ul className="trips-transfers">{mine.map((t) => <TransferRow key={`${t.from_member}-${t.to_member}`} group={group} transfer={t} meId={me?.id} onVenmo={onVenmo} onRecord={onRecord} onSettle={onSettle} onNudge={onNudge} request={request} paymentFlow={flow} />)}</ul>}
      {!!others.length && <>{!!mine.length && <h3 className="trips-subheading">Between others</h3>}
        <ul className="trips-transfers">{others.map((t) => <TransferRow key={`${t.from_member}-${t.to_member}`} group={group} transfer={t} meId={me?.id} onVenmo={onVenmo} onRecord={onRecord} onSettle={onSettle} onNudge={onNudge} request={request} paymentFlow={flow} />)}</ul></>}
    </>}

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


export function SettleGate({ group, me, onReady, onStart }) {
  const ready = group.settle.ready;
  const joined = group.members.filter(m => m.user_id);
  return <section className="trips-settle-gate">
    <p>Opens when everyone's done adding.</p>
    <ul>{joined.map(m => <li key={m.id}><strong>{firstName(m)}</strong><span>{!ready[m.id] ? 'Adding' : ready[m.id].by === m.id ? 'Done' : `Closed out by ${firstName(findMember(group, ready[m.id].by))}`}</span></li>)}</ul>
    <p>Waiting on {joined.filter(m => group.settle.waiting.includes(m.id)).map(firstName).join(', ')}</p>
    {me?.user_id && <Button variant={ready[me.id] ? 'ghost' : 'primary'} onClick={() => onReady(me.id, !ready[me.id])}>{ready[me.id] ? 'Not done yet' : 'Done adding'}</Button>}
    {me?.user_id === group.owner_id && <Button variant="ghost" onClick={onStart}>Start now</Button>}
  </section>;
}

function ChangedSinceSettling({ group, onActivity }) {
  if (!group.settle?.started_at || !group.obligations?.some(o => o.status === 'open' && o.created_at > group.settle.started_at)) return null;
  const changes = group.activity.filter(a => ['add_expense', 'edit_expense', 'delete_expense', 'restore_expense'].includes(a.kind) && a.at > group.settle.started_at).sort((a, b) => b.at.localeCompare(a.at));
  return <section className="trips-late-changes"><h3>Changed since settling</h3><ul>{changes.slice(0, 3).map(a => <li key={a.id}>{a.summary} · {money(a.amount_minor, group.currency)}</li>)}</ul>{changes.length > 3 && <button className="trips-text-button" onClick={onActivity}>+{changes.length - 3} more</button>}</section>;
}
