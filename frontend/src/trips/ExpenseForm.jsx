import React, { useState } from 'react';
import { Minus, Pencil, Plus, Trash2 } from 'lucide-react';
import { Bag, Bowl, Cabin, Camper, Ticket } from './doodles.jsx';
import { decimal, equalShares, money, shortDate, today, toMinor, weightedShares } from './money.js';
import { Avatar, Button, Field, Form } from './ui.jsx';
import { findMember, firstName, memberName, myMember } from './people.js';
import { paidAmounts, payersOf } from './balances.js';

export const categories = [
  { key: 'food', label: 'Food', icon: Bowl, color: '#b76845' },
  { key: 'stay', label: 'Stay', icon: Cabin, color: '#6e7b7e' },
  { key: 'transport', label: 'Transport', icon: Camper, color: '#69755a' },
  { key: 'activities', label: 'Activities', icon: Ticket, color: '#d39155' },
  { key: 'other', label: 'Other', icon: Bag, color: '#a08a66' },
];
export const categoryOf = (key) => categories.find((category) => category.key === key) || categories[4];

// A starting guess from the description; choosing a category yourself always wins.
const keywords = [
  ['food', /\b(dinner|lunch|breakfast|brunch|coffee|cafe|groceries|grocery|food|snacks?|drinks?|beer|wine|bar|restaurant|pizza|tacos?|dessert|meal)\b/],
  ['transport', /\b(gas|fuel|parking|uber|lyft|taxi|train|flights?|airfare|bus|ferry|tolls?|car|shuttle|metro|subway)\b/],
  ['stay', /\b(cabin|hotel|motel|airbnb|vrbo|hostel|lodge|lodging|campsite|camping|inn|resort|nights?)\b/],
  ['activities', /\b(tickets?|tour|museum|kayaks?|kayaking|ski|skiing|lift|surf|surfing|concert|hike|boat|lessons?|rentals?|golf|spa)\b/],
];
export function guessCategory(description) {
  const text = description.toLowerCase();
  return keywords.find(([, pattern]) => pattern.test(text))?.[0] || null;
}

// Percentages travel as basis points (12.5% = 1250) so they stay whole numbers.
// [key, label, short label for phones]
const modes = [['equal', 'Equally', 'Equal'], ['shares', 'By shares', 'Shares'], ['exact', 'Exact amounts', 'Amounts'], ['percent', 'By percent', 'Percent']];
const modeLabel = (key) => modes.find(([mode]) => mode === key)?.[1] || key;
const weightLabel = (expense, memberId) => (expense.split_mode === 'percent' ? `${expense.weights[memberId] / 100}%` : `${expense.weights[memberId]} sh`);
const toBasisPoints = (text) => { const value = Number(text); return /^\d{1,3}(\.\d{1,2})?$/.test(text.trim()) && value > 0 && value <= 100 ? Math.round(value * 100) : 0; };

// "You", "Alex", or "Alex +1" when several people paid. The biggest payer is paid_by.
export function payerLabel(group, expense, meId) {
  const payer = findMember(group, expense.paid_by);
  const others = Object.keys(paidAmounts(expense)).length - 1;
  return `${payer?.id === meId ? 'You' : firstName(payer)}${others ? ` +${others}` : ''}`;
}
// Every field that changes who owes what, so a conflict can be reviewed before overwriting it.
export function savedSummary(saved, group) {
  const name = (id) => memberName(group.members.find((m) => m.id === id));
  const split = group.members.filter((m) => saved.shares[m.id] !== undefined)
    .map((m) => `${name(m.id)} ${money(saved.shares[m.id], group.currency)}${saved.weights ? ` (${weightLabel(saved, m.id)})` : ''}`);
  const paid = payersOf(group, saved).map(([m, amount]) => (saved.payers ? `${name(m.id)} ${money(amount, group.currency)}` : name(m.id)));
  return [
    `${saved.description} · ${money(saved.amount_minor, group.currency)} · ${paid.join(', ')} paid`,
    `${modeLabel(saved.split_mode)}: ${split.join(', ')}`,
    `${shortDate(saved.date)} · ${categoryOf(saved.category).label}${saved.notes ? ` · “${saved.notes}”` : ''}`,
  ];
}

const parse = (value, allowZero, currency) => { try { return toMinor(value, allowZero, currency); } catch { return null; } };

const when = (iso) => new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });

// Tapping an expense shows it first; editing is a deliberate second step.
export function ExpenseDetail({ group, expense, meId, onEdit, onDelete, onClose }) {
  const { icon: Icon, color, label } = categoryOf(expense.category);
  const payers = payersOf(group, expense);
  const byUser = (userId) => group.members.find((m) => m.user_id === userId);
  const name = (m) => (m?.id === meId ? 'You' : memberName(m));
  const edited = expense.updated_at && expense.updated_at !== expense.created_at;
  return <div className="trips-detail">
    <div className="trips-detail-head"><span className="trips-category" style={{ '--chip': color }} aria-hidden="true"><Icon size={26} /></span>
      <div><strong>{money(expense.amount_minor, group.currency)}</strong><small>{label} · {shortDate(expense.date)}</small></div></div>
    <p className="trips-detail-paid">{expense.payers
      ? payers.map(([member, amount]) => `${name(member)} ${money(amount, group.currency)}`).join(' and ')
      : <><Avatar member={payers[0]?.[0]} size={22} />{name(payers[0]?.[0])}</>} paid · split {modeLabel(expense.split_mode).toLowerCase()}</p>
    <ul className="trips-detail-shares" aria-label="Who owes what">{group.members.filter((m) => expense.shares[m.id] !== undefined).map((m) =>
      <li key={m.id} className={m.id === meId ? 'trips-detail-me' : undefined}><span><Avatar member={m} size={26} />{name(m)}{expense.weights && <small>{weightLabel(expense, m.id)}</small>}</span>
        <strong>{money(expense.shares[m.id], group.currency)}</strong></li>)}</ul>
    {expense.notes && <p className="trips-note">{expense.notes}</p>}
    {expense.created_at && <p className="trips-muted trips-small">Added by {byUser(expense.created_by) ? memberName(byUser(expense.created_by)) : 'someone'}, {when(expense.created_at)}
      {edited && <> · edited by {byUser(expense.updated_by) ? memberName(byUser(expense.updated_by)) : 'someone'}, {when(expense.updated_at)}</>}</p>}
    <div className="trips-form-actions"><button type="button" className="trips-text-button trips-danger trips-form-aside" onClick={onDelete}><Trash2 size={14} aria-hidden="true" />Delete</button>
      <Button variant="ghost" onClick={onClose}>Close</Button><Button variant="primary" onClick={onEdit}><Pencil size={15} aria-hidden="true" />Edit</Button></div>
  </div>;
}

// `conflict` is set after a stale save: { latest } is the version now saved for this expense (null if deleted).
export function ExpenseForm({ group, user, expense, initial = {}, conflict, onSave, onCancel, onDelete }) {
  const me = myMember(group, user.id);
  const isMember = (id) => group.members.some((member) => member.id === id);
  // New expenses always start as "you paid, split equally with everyone", like Splitwise. Only links prefill more.
  const [id] = useState(() => expense?.id || crypto.randomUUID());
  const [description, setDescription] = useState(expense?.description ?? initial.description ?? '');
  const [amount, setAmount] = useState(expense ? decimal(expense.amount_minor) : initial.amount ?? '');
  const [paidBy, setPaidBy] = useState(expense?.paid_by || (isMember(initial.paid_by) && initial.paid_by) || me?.id || group.members[0].id);
  const [date, setDate] = useState(expense?.date || today());
  const [category, setCategory] = useState(expense?.category || initial.category || guessCategory(initial.description || '') || 'other');
  const [categoryChosen, setCategoryChosen] = useState(Boolean(expense || initial.category));
  const [notes, setNotes] = useState(expense?.notes || '');
  const [mode, setMode] = useState(expense?.split_mode || 'equal');
  const [participants, setParticipants] = useState(() => expense ? Object.keys(expense.shares)
    : initial.participants?.filter(isMember).length ? initial.participants.filter(isMember)
      : group.members.map((m) => m.id));
  const perMember = (value) => Object.fromEntries(group.members.map((m) => [m.id, value(m.id)]));
  const [exact, setExact] = useState(() => perMember((id) => (expense?.shares[id] === undefined ? '' : decimal(expense.shares[id]))));
  const [weights, setWeights] = useState(() => perMember((id) => String(expense?.split_mode === 'shares' && expense.weights?.[id] || 1)));
  const [percents, setPercents] = useState(() => perMember((id) => (expense?.split_mode === 'percent' && expense.weights?.[id] ? String(expense.weights[id] / 100) : '')));
  const [several, setSeveral] = useState(Boolean(expense?.payers));
  const [paidAmountsInput, setPaidAmountsInput] = useState(() => perMember((id) => (expense?.payers?.[id] ? decimal(expense.payers[id]) : '')));

  const total = parse(amount, false, group.currency) || 0;
  const selected = group.members.filter((m) => participants.includes(m.id));
  const weightOf = (memberId) => { const value = Number(weights[memberId]); return Number.isInteger(value) && value >= 1 && value <= 1000 ? value : 0; };
  // Blank percentages share whatever is left evenly, so a fresh percent split already adds up to 100%
  // and typing one person's figure rebalances the rest. The placeholder shows the figure that will save.
  const blank = (memberId) => !(percents[memberId] || '').trim();
  const blanks = selected.filter((m) => blank(m.id)).map((m) => m.id);
  const rest = Math.max(0, 10000 - selected.reduce((sum, m) => sum + (blank(m.id) ? 0 : toBasisPoints(percents[m.id])), 0));
  const basisPoints = Object.fromEntries(selected.map((m) => {
    const index = blanks.indexOf(m.id);
    return [m.id, index < 0 ? toBasisPoints(percents[m.id]) : Math.floor(rest / blanks.length) + Number(index < rest % blanks.length)];
  }));
  const percentLeft = 10000 - Object.values(basisPoints).reduce((a, b) => a + b, 0);
  const preview = mode === 'equal' ? equalShares(total, selected)
    : mode === 'shares' ? weightedShares(total, Object.fromEntries(selected.map((m) => [m.id, weightOf(m.id)])))
      : mode === 'percent' ? weightedShares(total, basisPoints)
        : Object.fromEntries(selected.map((m) => [m.id, parse(exact[m.id] || '0', true, group.currency) ?? 0]));
  const assigned = Object.values(preview).reduce((a, b) => a + b, 0);
  const payerParsed = group.members.map((m) => [m, (paidAmountsInput[m.id] || '').trim() ? parse(paidAmountsInput[m.id], true, group.currency) : 0]);
  const payerEntries = payerParsed.filter(([, value]) => value > 0).map(([m, value]) => [m.id, value]);
  const paidLeft = total - payerEntries.reduce((sum, [, value]) => sum + value, 0);
  const left = (value, unit) => (value ? `${unit(Math.abs(value))} ${value > 0 ? 'left to assign' : 'over'}` : 'Adds up.');
  const toggle = (memberId, on) => setParticipants(on ? group.members.map((m) => m.id).filter((x) => x === memberId || participants.includes(x)) : participants.filter((x) => x !== memberId));
  const step = (memberId, delta) => setWeights({ ...weights, [memberId]: String(Math.min(1000, Math.max(1, (weightOf(memberId) || 1) + delta))) });

  return <Form name="expense" submit={expense ? 'Save changes' : 'Save expense'} onCancel={onCancel}
    aside={expense && onDelete && <button type="button" className="trips-text-button trips-danger" onClick={onDelete}><Trash2 size={14} aria-hidden="true" />Delete</button>}
    onSubmit={async () => {
      const amountMinor = toMinor(amount, false, group.currency);
      if (!selected.length) throw new Error('Choose at least one person to split with.');
      let shares = {};
      if (mode === 'exact') {
        shares = Object.fromEntries(selected.map((m) => [m.id, toMinor(exact[m.id] || '0', true, group.currency)]));
        const sum = Object.values(shares).reduce((a, b) => a + b, 0);
        if (sum !== amountMinor) throw new Error(`Exact amounts must add up to ${money(amountMinor, group.currency)} (${money(Math.abs(amountMinor - sum), group.currency)} ${sum < amountMinor ? 'left' : 'over'}).`);
      } else if (mode === 'shares') {
        shares = Object.fromEntries(selected.map((m) => [m.id, weightOf(m.id)]));
        if (Object.values(shares).some((value) => !value)) throw new Error('Give each selected person a whole number of shares from 1 to 1000.');
      } else if (mode === 'percent') {
        shares = basisPoints;
        if (Object.values(shares).some((value) => !value) || percentLeft) throw new Error('Give each selected person a percentage; together they must add up to 100%.');
      }
      let payers = {};
      if (several) {
        const unreadable = payerParsed.find(([, value]) => value === null);
        if (unreadable) throw new Error(`Check the amount ${memberName(unreadable[0])} paid.`);
        if (payerEntries.length < 2 || paidLeft) throw new Error(`Enter what at least two people paid, adding up to ${money(amountMinor, group.currency)}.`);
        payers = Object.fromEntries(payerEntries);
      }
      // With several payers the server names the biggest one as paid_by.
      await onSave({ id, description: description.trim(), amount_minor: amountMinor, paid_by: several ? payerEntries[0][0] : paidBy, payers, date, category, notes,
        split_mode: mode, participants: selected.map((m) => m.id), shares, revision: group.revision });
    }}>
    {group.settle?.started && group.settle.started_at && <p className="trips-muted trips-small">Settling started. Saving changes who owes what.</p>}
    {conflict && expense && <div className="trips-note" role="status">{conflict.latest ? <>
      <strong>Someone else saved this first:</strong>
      <ul className="trips-conflict">{savedSummary(conflict.latest, group).map((line) => <li key={line}>{line}</li>)}</ul>
      Save to replace it with yours, or cancel to keep theirs.</> : 'Someone deleted this expense. Cancel to accept that.'}</div>}
    <div className="trips-form-grid trips-form-grid--lead">
      <Field label={`Amount (${group.currency})`}><input name="amount" className="trips-amount-input" autoFocus={!expense} inputMode="decimal" enterKeyHint="next" required autoComplete="off" placeholder="0.00" value={amount} onChange={(e) => setAmount(e.target.value)} /></Field>
      <Field label="Description"><input name="description" required maxLength={80} enterKeyHint="next" autoComplete="off" placeholder="Dinner, gas, cabin…" value={description} onChange={(e) => {
        setDescription(e.target.value);
        if (!categoryChosen) setCategory(guessCategory(e.target.value) || 'other');
      }} /></Field>
    </div>

    <fieldset className="trips-chips-field"><legend>Paid by</legend><div className="trips-chips">
      {group.members.map((m) => <label className="trips-chip" key={m.id}>
        <input type="radio" name="paid_by" value={m.id} checked={!several && paidBy === m.id} onChange={() => { setPaidBy(m.id); setSeveral(false); }} />
        <Avatar member={m} size={22} /><span>{m.id === me?.id ? 'You' : memberName(m)}</span>
      </label>)}
      <label className="trips-chip"><input type="radio" name="paid_by" value="several" checked={several} onChange={() => setSeveral(true)} /><span>Several people</span></label>
    </div>
    {several && <>{group.members.map((m) => <div className="trips-split-row" key={m.id}>
      <label htmlFor={`paid_${m.id}`}><Avatar member={m} size={26} /><span>{m.id === me?.id ? `${memberName(m)} (you)` : memberName(m)}</span></label>
      <input id={`paid_${m.id}`} name={`paid_${m.id}`} aria-label={`${memberName(m)} paid (${group.currency})`} inputMode="decimal" placeholder="0.00" value={paidAmountsInput[m.id]} onChange={(e) => setPaidAmountsInput({ ...paidAmountsInput, [m.id]: e.target.value })} />
    </div>)}
    <p className="trips-split-note" aria-live="polite">{left(paidLeft, (v) => money(v, group.currency))}</p></>}
    </fieldset>

    <fieldset className="trips-split"><legend>Split</legend>
      <div className="trips-segment" role="radiogroup" aria-label="Split method">{modes.map(([key, label, short]) => <label key={key}>
        <input type="radio" name="split_mode" value={key} aria-label={label} checked={mode === key} onChange={() => setMode(key)} /><span><small className="trips-long">{label}</small><small className="trips-short">{short}</small></span></label>)}</div>
      <div className="trips-split-quick" role="group" aria-label="Quick select">
        <button type="button" onClick={() => setParticipants(group.members.map((m) => m.id))}>Everyone</button>
        {me && <button type="button" onClick={() => setParticipants([me.id])}>Just me</button>}
        <span>{selected.length} of {group.members.length}</span>
      </div>
      {group.members.map((m) => {
        const on = participants.includes(m.id);
        return <div className={`trips-split-row${on ? '' : ' trips-split-row--off'}`} key={m.id}>
          <label><input type="checkbox" name="participants" value={m.id} checked={on} onChange={(e) => toggle(m.id, e.target.checked)} /><Avatar member={m} size={26} /><span>{m.id === me?.id ? `${memberName(m)} (you)` : memberName(m)}</span></label>
          {mode === 'percent' && <span className="trips-percent"><input name={`percent_${m.id}`} aria-label={`Percent for ${memberName(m)}`} inputMode="decimal" placeholder={on ? String((basisPoints[m.id] || 0) / 100) : '0'} disabled={!on} value={percents[m.id]} onChange={(e) => setPercents({ ...percents, [m.id]: e.target.value })} />%</span>}
          {mode === 'exact' && <input name={`share_${m.id}`} aria-label={`Amount for ${memberName(m)} (${group.currency})`} inputMode="decimal" placeholder="0.00" disabled={!on} value={exact[m.id]} onChange={(e) => setExact({ ...exact, [m.id]: e.target.value })} />}
          {mode === 'shares' && <span className="trips-stepper">
            <button type="button" aria-label={`Fewer shares for ${memberName(m)}`} disabled={!on || weightOf(m.id) <= 1} onClick={() => step(m.id, -1)}><Minus size={14} /></button>
            <input name={`weight_${m.id}`} aria-label={`Shares for ${memberName(m)}`} inputMode="numeric" disabled={!on} value={weights[m.id]} onChange={(e) => setWeights({ ...weights, [m.id]: e.target.value.replace(/\D/g, '').slice(0, 4) })} />
            <button type="button" aria-label={`More shares for ${memberName(m)}`} disabled={!on} onClick={() => step(m.id, 1)}><Plus size={14} /></button>
          </span>}
          {mode !== 'exact' && <span className="trips-split-amount">{on ? money(preview[m.id] || 0, group.currency) : '—'}</span>}
        </div>;
      })}
      <p className="trips-split-note" aria-live="polite">{mode === 'exact' ? left(total - assigned, (v) => money(v, group.currency))
        : mode === 'percent' ? left(percentLeft, (v) => `${v / 100}%`)
        : selected.length ? `${selected.length} ${selected.length === 1 ? 'person' : 'people'}` : 'Choose who shared this.'}</p>
    </fieldset>

    <fieldset className="trips-chips-field"><legend>Category</legend><div className="trips-chips">
      {categories.map(({ key, label, icon: Icon, color }) => <label className="trips-chip" key={key} style={{ '--chip': color }}>
        <input type="radio" name="category" value={key} checked={category === key} onChange={() => { setCategory(key); setCategoryChosen(true); }} /><Icon size={20} /><span>{label}</span>
      </label>)}
    </div></fieldset>

    <details className="trips-more" open={Boolean(expense?.notes) || date !== today()}>
      <summary>{shortDate(date)}{notes ? ' · note' : ''} <span>Date and note</span></summary>
      <div className="trips-form-grid">
        <Field label="Date"><input name="date" type="date" required value={date} onChange={(e) => setDate(e.target.value)} /></Field>
        <Field label="Note (optional)"><input name="notes" maxLength={1000} value={notes} onChange={(e) => setNotes(e.target.value)} placeholder="Details" /></Field>
      </div>
    </details>
  </Form>;
}
