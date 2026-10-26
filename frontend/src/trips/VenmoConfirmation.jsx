import React, { useState } from 'react';
import { Button, Field, Form } from './ui.jsx';
import VenmoProfile from './VenmoProfile.jsx';
import { normalizeUsername } from './venmo.js';

export default function VenmoConfirmation({ username, onConfirm, onCancel, request }) {
  const [editing, setEditing] = useState(!username);
  const [value, setValue] = useState(username || '');
  const [confirmedHandle, setConfirmedHandle] = useState('');
  const [previewedHandle, setPreviewedHandle] = useState('');
  let handle = '';
  try { handle = normalizeUsername(value); } catch { /* Validation is shown on submit. */ }
  return <section className="trips-venmo-confirmation">
    <h1>Confirm your Venmo</h1>
    <Form primaryFirst name="confirm_venmo" submit={editing ? 'Review handle' : "Yes, that's me"} submitDisabled={!editing && previewedHandle !== handle} onCancel={onCancel}
      aside={!editing && <Button type="button" variant="secondary" onClick={() => { setConfirmedHandle(''); setEditing(true); }}>No, it's not</Button>}
      onSubmit={async () => {
        const normalized = normalizeUsername(value);
        if (!normalized) throw new Error('Enter your Venmo username.');
        if (editing) { setEditing(false); return; }
        if (previewedHandle !== normalized) return;
        await onConfirm(normalized);
        setConfirmedHandle(normalized);
      }}>
      {editing && <Field label="Your Venmo username"><input name="venmo_username" autoFocus autoComplete="off" autoCapitalize="none" autoCorrect="off" spellCheck={false} value={value}
        onChange={(event) => { setConfirmedHandle(''); setValue(event.target.value); }} /></Field>}
      <VenmoProfile handle={handle} confirmed={Boolean(handle && handle === confirmedHandle)} request={request} debounce={350} onLoaded={setPreviewedHandle} />
      {!editing && handle && handle !== confirmedHandle && <p className="trips-venmo-prompt">Is this you?</p>}
    </Form>
  </section>;
}
