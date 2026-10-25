import React, { useEffect, useState } from 'react';
import { Button, Form } from './ui.jsx';

const FLAGS = { weak: 'Weak match', ambiguous: 'Several close matches', 'same account suggested twice': 'Also suggested for someone else' };
const candidates = (row) => (row.status === 'suggested' ? [row, ...row.alternatives] : row.alternatives);

// Admin-only review of name-match suggestions. Names only suggest; each link is its own explicit, explained step.
export default function LinkAccounts({ group, request, onLink, onClose }) {
  const [rows, setRows] = useState(null);
  const [error, setError] = useState('');
  const [choice, setChoice] = useState(null);
  const load = () => request(`/admin/groups/${group.id}/link-suggestions`)
    .then(setRows, (e) => setError(e.message));
  useEffect(() => { load(); }, [group.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (choice) {
    const { row, candidate } = choice;
    return <Form submit={`Link ${row.member_name}`} onCancel={() => setChoice(null)} onSubmit={async () => {
      await onLink(row.member_id, candidate.user_id, `Linked ${row.member_name} to ${candidate.account_name}.`);
      setChoice(null);
      await load();
    }}>
      <p>Link <strong>{row.member_name}</strong> on this trip to the account <strong>{candidate.account_name}</strong>?</p>
      <ul className="trips-link-effects">
        <li>That account gets full access to this trip and can add and edit expenses.</li>
        <li>{candidate.venmo_username ? <>Pay and Request for {row.member_name} will go to <strong>@{candidate.venmo_username}</strong>.</>
          : <>That account has no Venmo username yet.</>}</li>
        <li>Their pending invite link stops working. You can unlink later from their person menu.</li>
      </ul>
      <p className="trips-muted trips-small">Matching names isn’t proof. Only link someone you’ve confirmed is this person.</p>
    </Form>;
  }
  return <div className="trips-link-accounts">
    {error && <p className="trips-error" role="alert">{error}</p>}
    {!rows && !error && <p className="trips-muted" role="status">Finding possible accounts…</p>}
    {rows && !rows.length && <p className="trips-muted">Everyone on this trip is linked.</p>}
    {rows && rows.length > 0 && <ul className="trips-link-list">{rows.map((row) => <li key={row.member_id}>
      <strong>{row.member_name}</strong>
      {candidates(row).length ? <ul>{candidates(row).map((candidate) => <li key={candidate.user_id}>
        <span>{candidate.account_name}{candidate.venmo_username && <> · @{candidate.venmo_username}</>}
          <small className="trips-muted"> {candidate.basis}{candidate === row && row.flags.map((flag) => ` · ${FLAGS[flag] || flag}`).join('')}</small></span>
        <Button variant="ghost" onClick={() => setChoice({ row, candidate })} aria-label={`Review linking ${row.member_name} to ${candidate.account_name}`}>Review</Button>
      </li>)}</ul> : <small className="trips-muted">No likely account. Send them an invite link instead.</small>}
    </li>)}</ul>}
    <div className="trips-form-actions"><Button variant="primary" onClick={onClose}>Done</Button></div>
  </div>;
}
