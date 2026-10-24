import React, { useRef, useState } from 'react';
import { Link2, Pencil, Share2, UserPlus, UsersRound } from 'lucide-react';
import { money } from './money.js';
import { Avatar, Button, CopyButton, Field, Form } from './ui.jsx';
import { memberName } from './people.js';
import { normalizeUsername, venmoProfile } from './venmo.js';

export const splitNames = (text) => [...new Map(text.split(/[\n,]+/).map((name) => name.trim()).filter(Boolean).map((name) => [name.toLowerCase(), name])).values()];

export function AddPeopleForm({ onSave, onCancel }) {
  const [names, setNames] = useState('');
  const list = splitNames(names);
  return <Form name="add_people" submit={list.length > 1 ? `Add ${list.length} people` : 'Add person'} onCancel={onCancel} onSubmit={() => {
    if (!list.length) throw new Error('Enter at least one name.');
    if (list.some((name) => name.length > 80)) throw new Error('Keep each name under 80 characters.');
    return onSave(list);
  }}>
    <Field label="Names" hint="Separate several people with commas."><input name="names" autoFocus required autoComplete="off" placeholder="Alex, Sam, Jordan" value={names} onChange={(e) => setNames(e.target.value)} /></Field>
  </Form>;
}

export function InviteLinks({ links, onClose }) {
  return <div className="trips-invites">
    <p className="trips-muted">One link per person. Each works once.</p>
    <ul>{links.map(({ name, link }) => <li key={link}>
      <strong>{name}</strong><input readOnly aria-label={`Invite link for ${name}`} value={link} onFocus={(e) => e.target.select()} />
      <span>{navigator.share && <Button variant="ghost" onClick={() => navigator.share({ title: 'Join my trip', url: link }).catch(() => {})}><Share2 size={14} aria-hidden="true" />Share</Button>}<CopyButton value={link} label={`invite link for ${name}`} /></span>
    </li>)}</ul>
    <div className="trips-form-actions"><Button variant="primary" onClick={onClose}>Done</Button></div>
  </div>;
}

// Signed-in people manage their own username; the trip creator can fill one in for people who haven't joined.
export function VenmoForm({ initial, onSave, onCancel, hint }) {
  const [value, setValue] = useState(initial || '');
  const removing = useRef(false);
  // Remove goes through the same guarded submit as Save, so the two can't race.
  return <Form name="venmo_username" submit="Save" onCancel={onCancel} onSubmit={(action) => {
    const remove = action === 'remove' || removing.current;
    removing.current = false;
    return onSave(remove ? null : normalizeUsername(value) || null);
  }} aside={initial && <button type="submit" name="action" value="remove" formNoValidate className="trips-text-button trips-danger"
    onClick={() => { removing.current = true; }}>Remove</button>}>
    <Field label="Venmo username" hint={hint}><input name="venmo_username" autoFocus autoCapitalize="none" autoCorrect="off" spellCheck={false} autoComplete="off" placeholder="@username" value={value} onChange={(e) => setValue(e.target.value)} /></Field>
  </Form>;
}

export function PeoplePanel({ group, user, onAdd, onInvite, onEditVenmo, onEditProfile }) {
  const owner = group.owner_id === user.id;
  return <>
    <div className="trips-panel-heading"><h2 className="trips-section-heading"><UsersRound size={16} aria-hidden="true" />People</h2>
      {owner && <Button onClick={onAdd}><UserPlus size={16} aria-hidden="true" />Add people</Button>}</div>
    <ul className="trips-people">{group.members.map((m) => {
      const you = m.user_id === user.id;
      const balance = group.balances[m.id] || 0;
      return <li className="trips-person" key={m.id}>
        <Avatar member={m} size={40} />
        <div>
          <strong>{memberName(m)}{you && <span className="trips-you">you</span>}</strong>
          <small>{m.user_id === group.owner_id ? 'Created the trip' : m.user_id ? 'Joined' : 'Hasn’t joined'}
            {m.venmo_username && <> · <a className="trips-handle" href={venmoProfile(m.venmo_username)} target="_blank" rel="noopener noreferrer"
              aria-label={`${memberName(m)} on Venmo, @${m.venmo_username}`}>@{m.venmo_username}</a></>}</small>
        </div>
        <span className={`trips-person-balance ${balance < 0 ? 'trips-owe' : balance > 0 ? 'trips-positive' : ''}`}>{balance ? `${balance < 0 ? 'owes' : 'gets'} ${money(Math.abs(balance), group.currency)}` : 'square'}</span>
        <span className="trips-person-actions">
          {you && <Button variant="ghost" onClick={onEditProfile} aria-label="Edit your Venmo username"><Pencil size={14} aria-hidden="true" />Venmo</Button>}
          {owner && !m.user_id && <Button variant="ghost" onClick={() => onEditVenmo(m)} aria-label={`Set Venmo for ${memberName(m)}`}><Pencil size={14} aria-hidden="true" />Venmo</Button>}
          {owner && !m.user_id && <Button onClick={() => onInvite(m)} aria-label={`Invite ${memberName(m)}`}><Link2 size={14} aria-hidden="true" />Invite</Button>}
        </span>
      </li>;
    })}</ul>
    <p className="trips-muted trips-small">Anyone on the trip can add and edit expenses.</p>
  </>;
}
