import React, { useRef, useState } from 'react';
import { Link2, MoreHorizontal, Pencil, Settings, Share2, Trash2, Unlink, UserCheck, UserMinus, UserPlus, UsersRound } from 'lucide-react';
import { money } from './money.js';
import { Avatar, Button, CopyButton, Field, Form } from './ui.jsx';
import { firstName, isInvolved, memberName } from './people.js';
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

export const inviteMessage = ({ inviter, tripName, name, link }) =>
  `${inviter ? `${firstName({ name: inviter })} added you` : 'You’re invited'} to ${tripName} on Cozy Trips, as ${name}. This link is just for you: ${link}`;

export function InviteLinks({ links, tripName, inviter, onClose }) {
  return <div className="trips-invites">
    <p className="trips-muted">Send each person their own link. Each works once.</p>
    <ul>{links.map(({ name, link }) => {
      const message = inviteMessage({ inviter, tripName, name, link });
      return <li key={link}>
        <strong>{name}</strong><input readOnly aria-label={`Invite link for ${name}`} value={link} onFocus={(e) => e.target.select()} />
        <span>{navigator.share && <Button variant="ghost" onClick={() => navigator.share({ title: `Join ${tripName}`, text: message.replace(link, '').trim(), url: link }).catch(() => {})}><Share2 size={14} aria-hidden="true" />Share</Button>}
          <CopyButton value={message} label={`invite message for ${name}`}>Copy message</CopyButton><CopyButton value={link} label={`invite link for ${name}`}>Copy link</CopyButton></span>
      </li>;
    })}</ul>
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

export function PeoplePanel({ group, user, onAdd, onManage, onSettings, onEditProfile, onLinkAccounts }) {
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
        {you ? <Button variant="ghost" className="trips-person-action" onClick={onEditProfile} aria-label="Edit your Venmo username"><Pencil size={14} aria-hidden="true" />Venmo</Button>
          : owner && <Button variant="ghost" className="trips-person-action" onClick={() => onManage(m)} aria-label={`Manage ${memberName(m)}`}><MoreHorizontal size={18} aria-hidden="true" /></Button>}
      </li>;
    })}</ul>
    <p className="trips-muted trips-small">Anyone on the trip can add and edit expenses.</p>
    {owner && <button type="button" className="trips-text-button" onClick={onSettings}><Settings size={14} aria-hidden="true" />Trip settings</button>}
    {owner && onLinkAccounts && <button type="button" className="trips-text-button" onClick={onLinkAccounts}><UserCheck size={14} aria-hidden="true" />Link people to accounts</button>}
  </>;
}

// The creator's options for one person. Each choice opens its own small, reviewable step.
export function PersonSheet({ group, member, onInvite, onVenmo, onRename, onRemove, onUnlink }) {
  const joined = Boolean(member.user_id);
  const busy = isInvolved(group, member.id);
  return <div className="trips-person-sheet">
    <div className="trips-venmo-who"><Avatar member={member} size={44} />
      <span className="trips-muted">{joined ? 'Joined' : 'Hasn’t joined'}{member.venmo_username ? ` · @${member.venmo_username}` : ''}</span></div>
    <ul className="trips-menu">
      {!joined && <li><button type="button" onClick={onInvite}><Link2 size={16} aria-hidden="true" /><span>New invite link<small>Older links for {firstName(member)} stop working.</small></span></button></li>}
      {!joined && <li><button type="button" onClick={onVenmo}><Pencil size={16} aria-hidden="true" /><span>{member.venmo_username ? 'Change Venmo username' : 'Add Venmo username'}<small>Until {firstName(member)} joins and adds their own.</small></span></button></li>}
      {!joined && <li><button type="button" onClick={onRename}><Pencil size={16} aria-hidden="true" /><span>Rename</span></button></li>}
      {joined && onUnlink && member.user_id !== group.owner_id && <li><button type="button" onClick={onUnlink}><Unlink size={16} aria-hidden="true" /><span>Unlink account
        <small>For a wrong link. {firstName(member)} keeps their history and gets a new invite link.</small></span></button></li>}
      <li><button type="button" className="trips-danger" disabled={busy} onClick={onRemove}><UserMinus size={16} aria-hidden="true" /><span>Remove from trip
        {busy && <small>On expenses or payments. Take {firstName(member)} off those first.</small>}</span></button></li>
    </ul>
    {joined && <p className="trips-muted trips-small">{firstName(member)} manages their own name and Venmo from their profile.</p>}
  </div>;
}

export function RenameForm({ label, initial, onSave, onCancel, aside = null, children = null }) {
  const [value, setValue] = useState(initial);
  return <Form name="rename" submit="Save name" aside={aside} onCancel={onCancel} onSubmit={() => {
    if (!value.trim()) throw new Error('Enter a name.');
    return onSave(value.trim());
  }}>
    <Field label={label}><input name="name" autoFocus required maxLength={80} autoComplete="off" value={value} onChange={(e) => setValue(e.target.value)} /></Field>
    {children}
  </Form>;
}

export function TripSettings({ group, onRename, onDelete, onCancel }) {
  return <RenameForm label="Trip name" initial={group.name} onSave={onRename} onCancel={onCancel}
    aside={<button type="button" className="trips-text-button trips-danger" onClick={onDelete}><Trash2 size={14} aria-hidden="true" />Delete trip</button>}>
    <p className="trips-muted trips-small">Deleting removes the trip, its expenses and its payments for everyone.</p>
  </RenameForm>;
}
