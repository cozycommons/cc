import React, { useState } from 'react';
import { Minus, Pencil, Plus, Trash2 } from 'lucide-react';
import { Bag, Bowl, Cabin, Camper, Ticket } from './doodles.jsx';
import { decimal, equalShares, money, shortDate, today, toMinor, weightedShares } from './money.js';
import { Avatar, Button, Field, Form } from './ui.jsx';
import { findMember, memberName, myMember } from './people.js';

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

const modes = [['equal', 'Equally'], ['shares', 'By shares'], ['exact', 'Exact amounts']];
// Every field that changes who owes what, so a conflict can be reviewed before overwriting it.
export function savedSummary(saved, group) {
  const name = (id) => memberName(group.members.find((m) => m.id === id));
  const split = group.members.filter((m) => saved.shares[m.id] !== undefined)
    .map((m) => `${name(m.id)} ${money(saved.shares[m.id], group.currency)}${saved.weights ? ` (${saved.weights[m.id]} sh)` : ''}`);
  return [
    `${saved.description} · ${money(saved.amount_minor, group.currency)} · ${name(saved.paid_by)} paid`,
    `${modes.find(([key]) => key === saved.split_mode)?.[1] || saved.split_mode}: ${split.join(', ')}`,
    `${shortDate(saved.date)} · ${categoryOf(saved.category).label}${saved.notes ? ` · “${saved.notes}”` : ''}`,
  ];
}

const parse = (value, allowZero, currency) => { try { return toMinor(value, allowZero, currency); } catch { return null; } };

const when = (iso) => new Date(iso).toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' });

// Tapping an expense shows it first; editing is a deliberate second step.
export function ExpenseDetail({ group, expense, meId, onEdit, onDelete, onClose }) {
  const { icon: Icon, color, label } = categoryOf(expense.category);
  const payer = findMember(group, expense.paid_by);
  const byUser = (userId) => group.members.find((m) => m.user_id === userId);
  const name = (m) => (m?.id === meId ? 'You' : memberName(m));
  const edited = expense.updated_at && expense.updated_at !== expense.created_at;
  return <div className="trips-detail">
    <div className="trips-detail-head"><span className="trips-category" style={{ '--chip': color }} aria-hidden="true"><Icon size={26} /></span>
      <div><strong>{money(expense.amount_minor, group.currency)}</strong><small>{label} · {shortDate(expense.date)}</small></div></div>
    <p className="trips-detail-paid"><Avatar member={payer} size={22} />{name(payer)} paid · split {modes.find(([key]) => key === expense.split_mode)?.[1].toLowerCase()}</p>
    <ul className="trips-detail-shares" aria-label="Who owes what">{group.members.filter((m) => expense.shares[m.id] !== undefined).map((m) =>
      <li key={m.id} className={m.id === meId ? 'trips-detail-me' : undefined}><span><Avatar member={m} size={26} />{name(m)}{expense.weights && <small>{expense.weights[m.id]} sh</small>}</span>
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
  const [exact, setExact] = useState(() => Object.fromEntries(group.members.map((m) => [m.id, expense?.shares[m.id] === undefined ? '' : decimal(expense.shares[m.id])])));
  const [weights, setWeights] = useState(() => Object.fromEntries(group.members.map((m) => [m.id, String(expense?.weights?.[m.id] || 1)])));

  const total = parse(amount, false, group.currency) || 0;
  const selected = group.members.filter((m) => participants.includes(m.id));
  const weightOf = (memberId) => { const value = Number(weights[memberId]); return Number.isInteger(value) && value >= 1 && value <= 1000 ? value : 0; };
  const preview = mode === 'equal' ? equalShares(total, selected)
    : mode === 'shares' ? weightedShares(total, Object.fromEntries(selected.map((m) => [m.id, weightOf(m.id)])))
      : Object.fromEntries(selected.map((m) => [m.id, parse(exact[m.id] || '0', true, group.currency) ?? 0]));
  const assigned = Object.values(preview).reduce((a, b) => a + b, 0);
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
      }
      await onSave({ id, description: description.trim(), amount_minor: amountMinor, paid_by: paidBy, date, category, notes,
        split_mode: mode, participants: selected.map((m) => m.id), shares, revision: group.revision });
    }}>
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
        <input type="radio" name="paid_by" value={m.id} checked={paidBy === m.id} onChange={() => setPaidBy(m.id)} />
        <Avatar member={m} size={22} /><span>{m.id === me?.id ? 'You' : memberName(m)}</span>
      </label>)}
    </div></fieldset>

    <fieldset className="trips-split"><legend>Split</legend>
      <div className="trips-segment" role="radiogroup" aria-label="Split method">{modes.map(([key, label]) => <label key={key}>
        <input type="radio" name="split_mode" value={key} checked={mode === key} onChange={() => setMode(key)} /><span>{label}</span></label>)}</div>
      <div className="trips-split-quick" role="group" aria-label="Quick select">
        <button type="button" onClick={() => setParticipants(group.members.map((m) => m.id))}>Everyone</button>
        {me && <button type="button" onClick={() => setParticipants([me.id])}>Just me</button>}
        <button type="button" onClick={() => setParticipants([])}>Clear</button>
        <span>{selected.length} of {group.members.length}</span>
      </div>
      {group.members.map((m) => {
        const on = participants.includes(m.id);
        return <div className={`trips-split-row${on ? '' : ' trips-split-row--off'}`} key={m.id}>
          <label><input type="checkbox" name="participants" value={m.id} checked={on} onChange={(e) => toggle(m.id, e.target.checked)} /><Avatar member={m} size={26} /><span>{m.id === me?.id ? `${memberName(m)} (you)` : memberName(m)}</span></label>
          {mode === 'exact' && <input name={`share_${m.id}`} aria-label={`Amount for ${memberName(m)} (${group.currency})`} inputMode="decimal" placeholder="0.00" disabled={!on} value={exact[m.id]} onChange={(e) => setExact({ ...exact, [m.id]: e.target.value })} />}
          {mode === 'shares' && <span className="trips-stepper">
            <button type="button" aria-label={`Fewer shares for ${memberName(m)}`} disabled={!on || weightOf(m.id) <= 1} onClick={() => step(m.id, -1)}><Minus size={14} /></button>
            <input name={`weight_${m.id}`} aria-label={`Shares for ${memberName(m)}`} inputMode="numeric" disabled={!on} value={weights[m.id]} onChange={(e) => setWeights({ ...weights, [m.id]: e.target.value.replace(/\D/g, '').slice(0, 4) })} />
            <button type="button" aria-label={`More shares for ${memberName(m)}`} disabled={!on} onClick={() => step(m.id, 1)}><Plus size={14} /></button>
          </span>}
          {mode !== 'exact' && <span className="trips-split-amount">{on ? money(preview[m.id] || 0, group.currency) : '—'}</span>}
        </div>;
      })}
      <p className="trips-split-note" aria-live="polite">{mode === 'exact'
        ? total === assigned ? 'Adds up.' : `${money(Math.abs(total - assigned), group.currency)} ${assigned < total ? 'left to assign' : 'over'}`
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
