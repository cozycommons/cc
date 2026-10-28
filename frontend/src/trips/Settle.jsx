import VenmoProfile from './VenmoProfile.jsx';
import React, { useEffect, useRef, useState } from 'react';
import { ArrowRight, Check, ExternalLink, HandCoins, Plus, Trash2 } from 'lucide-react';
import { decimal, money, shortDate, today, toMinor } from './money.js';
import { Avatar, Button, CopyButton, Field, Form } from './ui.jsx';
import { findMember, firstName, memberName } from './people.js';
import { normalizeUsername, settlementRole, tripNote } from './venmo.js';
import { balanceBreakdown } from './balances.js';
import { CheckInVenmo, PaymentPrompt, useVenmoPayment, VenmoOpenLink } from './VenmoPayment.jsx';
import { ConfirmationMark } from './ConfirmedVenmo.jsx';

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
  // The payment flow is shared by the whole trip; only a payment opened for this pair and role belongs to this sheet.
  const ours = Boolean(flow.opened && flow.opened.from_member === transfer.from_member && flow.opened.to_member === transfer.to_member && flow.opened.role === role);
  const opened = ours ? flow.opened : null;
  const pending = ours ? flow.pending : null;
  const shown = opened && pending ? pending : obligation || transfer;
  const shownAmount = shown.amount_minor;
  const changed = Boolean(group.obligations && !opened && !obligation);
  const note = [tripNote(group.name), pending?.reference || obligation?.reference].filter(Boolean).join(' · ');
  const settle = () => {
    if ((opened && !pending) || changed) throw new Error('This payment changed.');
    return group.obligations && (pending || obligation) && onSettle ? onSettle(pending || obligation) : onRecord({ id, from_member: transfer.from_member, to_member: transfer.to_member, amount_minor: transfer.amount_minor, date: today(), notes: 'Venmo', revision: group.revision });
  };
  const amount = decimal(shownAmount);
  const usd = group.currency === 'USD';
  const canAddHandle = usd && !username && onSaveHandle && !other?.user_id;
  if (changed) return <><p>This payment changed.</p><Button onClick={onCancel}>Close</Button></>;
  return <Form name="venmo" submit={ours && flow.returned ? null : role === 'pay' ? 'Sent' : 'Got it'} submitVariant="primary"
    onCancel={onCancel} onSubmit={settle}>
    {!username && <p className="trips-muted">No Venmo username yet</p>}
    <VenmoProfile handle={username} request={request} confirmedName={other?.venmo_confirmed_name} confirmed={other?.venmo_confirmed} />
    {obligation && group.settle?.started_at && obligation.created_at > group.settle.started_at && <small className="trips-updated">Updated</small>}
    <strong className="trips-venmo-amount">{money(shownAmount, group.currency)}</strong>
    {usd && username && <VenmoOpenLink className="cc-button cc-button--primary trips-venmo-open" payment={{ username, role, amountMinor: shownAmount, note }}
      onOpen={() => flow.open(pending || payment, role, username)}>{role === 'pay' ? `Pay ${money(shownAmount, group.currency)} in Venmo` : `Request ${money(shownAmount, group.currency)} in Venmo`} <ExternalLink size={14} aria-hidden="true" /></VenmoOpenLink>}
    {canAddHandle && <InlineHandle name={firstName(other)} onSave={onSaveHandle} />}
    {usd && !username && !canAddHandle && <p className="trips-muted">{firstName(other)} hasn’t added a Venmo username. {other?.user_id ? `Ask ${firstName(other)} to add it in their profile, or` : 'Ask the trip creator to add it, or'} pay with the details below.</p>}
    {!usd && <p className="trips-muted">Venmo only sends US dollars. Use the details below with another app.</p>}
    <dl className="trips-venmo-details">
      {username && <div><dt>To</dt><dd>@{username}</dd><CopyButton value={username} label="Venmo username" /></div>}
      <div><dt>Amount</dt><dd>{money(shownAmount, group.currency)}</dd><CopyButton value={amount} label="amount" /></div>
      <div><dt>Note</dt><dd>{note}</dd><CopyButton value={note} label="note" /></div>
    </dl>
    {ours && <PaymentPrompt flow={flow} group={group} onSettle={() => settle()} />}
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

const Name = ({ member, label, mark }) => <span className="trips-payment-name"><strong>{label}</strong>{mark && member?.venmo_confirmed && member.venmo_username && <ConfirmationMark />}</span>;
const isUpdated = (group, obligation) => Boolean(obligation && group.settle?.started_at && obligation.created_at > group.settle.started_at);

// One row per payment. Everyone sees every row; only the two people in it get an action.
function PaymentRow({ group, payment, meId, onVenmo, onRecord, onUndo, onNudge, paymentFlow }) {
  const { transfer, obligation, paid } = payment;
  const amountMinor = obligation?.amount_minor ?? transfer.amount_minor;
  const role = settlementRole(transfer, meId);
  const from = findMember(group, transfer.from_member);
  const to = findMember(group, transfer.to_member);
  const other = role === 'request' ? from : to;
  const usd = group.currency === 'USD';
  const label = (m) => (m?.id === meId ? 'You' : firstName(m));
  const open = () => (usd ? onVenmo(transfer, role) : onRecord(transfer));
  const recordLabel = `Record payment from ${memberName(from)} to ${memberName(to)}`;
  const nudgeable = role === 'request' && obligation && !paid && Date.now() - Date.parse(obligation.created_at) >= 3 * 86400000
    && (!obligation.nudged_at || Date.now() - Date.parse(obligation.nudged_at) >= 48 * 3600000);
  // The checkmark matters on the person you'd pay or request, so only your own rows show it.
  const people = <span className="trips-payment-names"><Name member={from} label={label(from)} mark={Boolean(role) && other === from} /><ArrowRight size={14} aria-label="to" /><Name member={to} label={label(to)} mark={Boolean(role) && other === to} /></span>;
  return <li className={`trips-payment${role ? ' trips-payment--mine' : ''}${paid ? ' trips-payment--paid' : ''}`}>
    {role && !paid ? <button type="button" className="trips-payment-who" onClick={open} aria-label={`Open payment ${label(from)} to ${label(to)}, ${money(amountMinor, group.currency)}`}>{people}</button>
      : <span className="trips-payment-who">{people}</span>}
    <strong className="trips-payment-amount">{money(amountMinor, group.currency)}</strong>
    <span className="trips-payment-status">{paid ? <><Check size={13} aria-hidden="true" />Paid</> : 'Open'}{isUpdated(group, obligation) && <small className="trips-updated">Updated</small>}</span>
    <span className="trips-payment-actions">
      {paid && role && onUndo && <button type="button" className="trips-text-button" onClick={() => onUndo(obligation)}
        aria-label={`Undo payment from ${memberName(from)} to ${memberName(to)}, ${money(amountMinor, group.currency)}`}>Undo</button>}
      {nudgeable && <button type="button" className="trips-text-button" onClick={() => onNudge?.(obligation)}>Nudge</button>}
      {!paid && role === 'pay' && <Button variant="primary" onClick={open} aria-label={usd ? `Pay ${memberName(to)} with Venmo` : recordLabel}>{usd ? 'Pay' : 'Paid'}</Button>}
      {!paid && role === 'request' && (usd && other?.venmo_username && obligation
        ? <VenmoOpenLink className="cc-button cc-button--secondary" payment={{ username: other.venmo_username, role, amountMinor, note: tripNote(group.name), reference: obligation.reference }}
          onOpen={() => paymentFlow.open(obligation, role, other.venmo_username)} ariaLabel={`Request ${money(amountMinor, group.currency)} from @${other.venmo_username}`}>Request</VenmoOpenLink>
        : <Button variant="secondary" onClick={open} aria-label={usd ? `Request from ${memberName(from)} with Venmo` : recordLabel}>{usd ? 'Request' : 'Received'}</Button>)}
    </span>
  </li>;
}

// Open payments first, then paid; your own rows before everyone else's.
function paymentRows(group, meId) {
  const open = group.transfers.map((t) => ({ transfer: t, paid: false,
    obligation: group.obligations?.find(o => o.status === 'open' && o.from_member === t.from_member && o.to_member === t.to_member) }));
  const paid = (group.obligations || []).filter(o => o.status === 'settled').map(o => ({ transfer: o, obligation: o, paid: true }));
  const rank = (row) => (row.paid ? 2 : 0) + (settlementRole(row.transfer, meId) ? 0 : 1);
  return [...open, ...paid].sort((a, b) => rank(a) - rank(b));
}

export function BalancesPanel({ group, me, profile, onVenmo, onRecord, onRemoveRepayment, onEditProfile, onSettle, onUndo, onNudge, request, paymentFlow, onReady, onStart, onCloseOut, onActivity }) {
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
  const rows = paymentRows(group, me?.id);
  // Settled Venmo payments live in the table above; this list keeps payments recorded by hand.
  const recorded = group.repayments.filter((p) => !group.obligations?.some(o => o.id === p.id && o.status === 'settled'));
  const owedWithoutHandle = myBalance > 0 && group.currency === 'USD' && profile && !profile.venmo_username;
  return <>
    {!paymentFlow && <PaymentPrompt flow={flow} group={group} onSettle={onSettle} />}
    {me && <section className={`trips-hero trips-hero--${myBalance < 0 ? 'owe' : myBalance > 0 ? 'owed' : 'even'}${celebrate ? ' trips-hero--celebrate' : ''}`} aria-label="Your balance">
      <span>{myBalance < 0 ? started ? 'You owe' : 'You owe so far' : myBalance > 0 ? started ? 'You’re owed' : 'You’re owed so far' : 'You’re all square'}</span>
      {myBalance !== 0 ? <strong>{money(Math.abs(myBalance), group.currency)}</strong> : <SquareStamp />}
      {owedWithoutHandle && <button type="button" className="trips-text-button" onClick={onEditProfile}>Add your Venmo to get paid</button>}
    </section>}

    {!started ? <ReadyPanel group={group} me={me} onReady={onReady} onStart={onStart} onCloseOut={onCloseOut} /> : <>
      <ChangedSinceSettling group={group} onActivity={onActivity} />
    <div className="trips-panel-heading"><h2 className="trips-section-heading"><HandCoins size={16} aria-hidden="true" />Settle up</h2></div>
    {!!group.transfers.length && <p className="trips-muted trips-small trips-settle-note">{group.settlement === 'fewest'
      ? 'The fewest payments to square everyone.'
      : 'These square everyone with the least money changing hands.'}</p>}
    {!rows.length ? <div className="trips-empty trips-empty--square">{!me && <SquareStamp />}<p>All square. Nobody owes anybody.</p></div> : <>
      <ul className="trips-payments" aria-label="Payments">{rows.map((row) => <PaymentRow key={row.paid ? row.obligation.id : `${row.transfer.from_member}-${row.transfer.to_member}`}
        group={group} payment={row} meId={me?.id} onVenmo={onVenmo} onRecord={onRecord} onUndo={onUndo} onNudge={onNudge} paymentFlow={flow} />)}</ul>
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
    {!recorded.length ? !rows.some(r => r.paid) && <p className="trips-muted">No payments yet.</p> : <ul className="trips-repayments">{recorded.slice().reverse().map((p) => {
      const from = findMember(group, p.from_member);
      const to = findMember(group, p.to_member);
      const settled = group.obligations?.find(o => o.id === p.id && o.status === 'settled');
      return <li key={p.id}><Avatar member={from} size={26} /><div><strong>{memberName(from)} → {memberName(to)}</strong><small>{shortDate(p.date)}{settled ? ` · Settled by ${memberName(findMember(group, settled.settled_by))}` : p.notes && ` · ${p.notes}`}</small></div>
        <strong>{money(p.amount_minor, group.currency)}</strong>
        <button className="trips-text-button" aria-label={`${settled ? 'Undo' : 'Remove'} payment from ${memberName(from)} to ${memberName(to)}, ${money(p.amount_minor, group.currency)} on ${p.date}`} onClick={() => group.obligations?.some(o => o.id === p.id && o.status === 'settled') && onUndo ? onUndo(group.obligations.find(o => o.id === p.id)) : onRemoveRepayment(p)}><Trash2 size={14} aria-hidden="true" />{group.obligations?.some(o => o.id === p.id && o.status === 'settled') ? 'Undo' : 'Remove'}</button></li>;
    })}</ul>}
  </>;
}


// Before settling starts: one clear "I'm done" button and who else is done.
export function ReadyPanel({ group, me, onReady, onStart, onCloseOut }) {
  const ready = group.settle.ready;
  const joined = group.members.filter(m => m.user_id);
  const mine = me?.user_id && ready[me.id];
  const status = (m) => !ready[m.id] ? 'Still adding' : ready[m.id].by === m.id ? 'Done' : `Closed out by ${firstName(findMember(group, ready[m.id].by))}`;
  return <section className="trips-ready" aria-label="Who's done adding">
    {me?.user_id && (!mine
      ? <Button variant="primary" className="trips-ready-button" onClick={() => onReady(me.id, true)}><Check size={20} aria-hidden="true" />Finished adding all bills</Button>
      : <div className="trips-ready-mine"><span><Check size={18} aria-hidden="true" />You're done adding</span>
        <button type="button" className="trips-text-button" onClick={() => onReady(me.id, false)}>Not done yet</button></div>)}
    <h3 className="trips-subheading">Who's done</h3>
    <ul className="trips-ready-table">{joined.map(m => <li key={m.id} className={ready[m.id] ? 'trips-ready-row--done' : ''}>
      <Avatar member={m} size={28} /><strong>{m.id === me?.id ? 'You' : memberName(m)}</strong>
      <span className="trips-ready-status">{ready[m.id] && <Check size={14} aria-hidden="true" />}{status(m)}</span>
      {!ready[m.id] && m.id !== me?.id && me?.user_id && onCloseOut
        ? <button type="button" className="trips-text-button" onClick={() => onCloseOut(m)} aria-label={`Close out ${firstName(m)}`}>Close out</button> : <span />}
    </li>)}</ul>
    <p className="trips-muted trips-small">Payments open when everyone's done.</p>
    {me?.user_id === group.owner_id && <Button variant="ghost" onClick={onStart}>Start now</Button>}
  </section>;
}

function ChangedSinceSettling({ group, onActivity }) {
  if (!group.settle?.started_at || !group.obligations?.some(o => o.status === 'open' && o.created_at > group.settle.started_at)) return null;
  const changes = group.activity.filter(a => ['add_expense', 'edit_expense', 'delete_expense', 'restore_expense'].includes(a.kind) && a.at > group.settle.started_at).sort((a, b) => b.at.localeCompare(a.at));
  return <section className="trips-late-changes"><h3>Changed since settling</h3><ul>{changes.slice(0, 3).map(a => <li key={a.id}>{a.summary} · {money(a.amount_minor, group.currency)}</li>)}</ul>{changes.length > 3 && <button className="trips-text-button" onClick={onActivity}>+{changes.length - 3} more</button>}</section>;
}
