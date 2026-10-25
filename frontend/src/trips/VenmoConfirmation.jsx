import React, { useState } from 'react';
import { Button, Field, Form } from './ui.jsx';
import { normalizeUsername, venmoProfile } from './venmo.js';

export default function VenmoConfirmation({ username, onConfirm, onCancel }) {
  const [editing, setEditing] = useState(!username);
  const [value, setValue] = useState(username || '');
  let handle = '';
  try { handle = normalizeUsername(value); } catch { /* Validation is shown on submit. */ }
  return <section className="trips-venmo-confirmation">
    <h1>Confirm your Venmo</h1>
    <Form name="confirm_venmo" submit="Yes, that's my Venmo" onCancel={onCancel} onSubmit={() => {
      const normalized = normalizeUsername(value);
      if (!normalized) throw new Error('Enter your Venmo username.');
      return onConfirm(normalized);
    }}>
      <p className="trips-muted">Open your profile to check your name and photo.</p>
      {handle && <a className="cc-button cc-button--secondary" href={venmoProfile(handle)} target="_blank" rel="noopener noreferrer">@{handle}</a>}
      {editing
        ? <Field label="Your Venmo username"><input name="venmo_username" autoComplete="off" autoCapitalize="none" spellCheck={false} value={value} onChange={(event) => setValue(event.target.value)} /></Field>
        : <Button type="button" variant="ghost" onClick={() => setEditing(true)}>Fix handle</Button>}
    </Form>
  </section>;
}
