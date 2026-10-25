import React, { useEffect, useState } from 'react';
import { Avatar, Button, Form } from './ui.jsx';

const FLAGS = { weak: 'Weak match', ambiguous: 'Several close matches', 'same account suggested twice': 'Also suggested for someone else' };
const candidates = (row) => (row.status === 'suggested' ? [row, ...row.alternatives] : row.alternatives);
const AccountChip = ({ candidate }) => <span className="trips-link-account"><Avatar member={{ avatar_url: candidate.avatar_url, name: candidate.account_name }} size={28} />
  <span>{candidate.account_name}{candidate.venmo_username && <span className="trips-link-handle">@{candidate.venmo_username}</span>}</span></span>;

// Admin-only review of name-match suggestions. Names only suggest; each link is its own explicit, explained step.
export default function LinkAccounts({ group, request, onLink, onClose }) {
  const [review, setReview] = useState(null);
  const [error, setError] = useState('');
  const [choice, setChoice] = useState(null);
  const load = () => request(`/admin/groups/${group.id}/link-suggestions`)
    .then(setReview, (e) => setError(e.message));
  const rows = review?.members;
  useEffect(() => { load(); }, [group.id]); // eslint-disable-line react-hooks/exhaustive-deps

  if (choice) {
    const { row, candidate } = choice;
    return <Form submit={`Link ${row.member_name}`} onCancel={() => setChoice(null)} onSubmit={async () => {
      setError('');
      try {
        // The revision these suggestions describe: if the trip changed since, this conflicts instead of linking.
        await onLink(row.member_id, candidate.user_id, review.revision, `Linked ${row.member_name} to ${candidate.account_name}.`);
      } catch (e) {
        setError(`${e.message} The suggestions below are refreshed; review again.`);
      }
      setChoice(null);
      await load();
    }}>
      <p>Link <strong>{row.member_name}</strong> on this trip to this account?</p>
      <AccountChip candidate={candidate} />
      <ul className="trips-link-effects">
        <li>That account gets full access to this trip and can add and edit expenses.</li>
        <li>{candidate.venmo_username ? <>Pay and Request for {row.member_name} will go to <strong>@{candidate.venmo_username}</strong>.</>
          : <>That account has no Venmo username yet.</>}</li>
        <li>Their pending invite link stops working. You can unlink later from their person menu.</li>
      </ul>
    </Form>;
  }
  return <div className="trips-link-accounts">
    {error && <p className="trips-error" role="alert">{error}</p>}
    {!rows && !error && <p className="trips-muted" role="status">Finding possible accounts…</p>}
    {rows && !rows.length && <p className="trips-muted">Everyone on this trip is linked.</p>}
    {rows && rows.length > 0 && <ul className="trips-link-list">{rows.map((row) => <li key={row.member_id}>
      <strong>{row.member_name}</strong>
      {candidates(row).length ? <ul>{candidates(row).map((candidate) => <li key={candidate.user_id}>
        <span><AccountChip candidate={candidate} />
          <small className="trips-muted"> {candidate.basis}{candidate === row && row.flags.map((flag) => ` · ${FLAGS[flag] || flag}`).join('')}</small>
          {candidate.lookalike && <small className="trips-muted">Can’t be told apart from another account with this name. Send {row.member_name} an invite link instead.</small>}</span>
        <Button variant="ghost" disabled={candidate.lookalike} onClick={() => setChoice({ row, candidate })}
          aria-label={`Review linking ${row.member_name} to ${candidate.account_name}`}>Review</Button>
      </li>)}</ul> : <small className="trips-muted">No likely account. Send them an invite link instead.</small>}
    </li>)}</ul>}
    <div className="trips-form-actions"><Button variant="primary" onClick={onClose}>Done</Button></div>
  </div>;
}
