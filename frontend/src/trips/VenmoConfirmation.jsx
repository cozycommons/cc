import React, { useState } from 'react';
import { Button, Field, Form } from './ui.jsx';
import VenmoProfile from './VenmoProfile.jsx';
import { normalizeUsername } from './venmo.js';

export default function VenmoConfirmation({ username, onConfirm, onCancel, request }) {
  const [editing, setEditing] = useState(!username);
  const [value, setValue] = useState(username || '');
  let handle = '';
  try { handle = normalizeUsername(value); } catch { /* Validation is shown on submit. */ }
  return <section className="trips-venmo-confirmation">
    <h1>Confirm your Venmo</h1>
    <Form primaryFirst name="confirm_venmo" submit={editing ? 'Save handle' : "Yes, that's me"} onCancel={onCancel} aside={!editing && <Button type="button" variant="ghost" className="trips-change-handle" onClick={() => setEditing(true)}>Change handle</Button>} onSubmit={() => {
      const normalized = normalizeUsername(value);
      if (!normalized) throw new Error('Enter your Venmo username.');
      return onConfirm(normalized);
    }}>
      {editing && <Field label="Your Venmo username"><input name="venmo_username" autoFocus autoComplete="off" autoCapitalize="none" autoCorrect="off" spellCheck={false} value={value} onChange={(event) => setValue(event.target.value)} /></Field>}
      <VenmoProfile handle={handle} request={request} debounce={350} />
      {!editing && handle && <p className="trips-venmo-prompt">Is this you?</p>}
    </Form>
  </section>;
}
