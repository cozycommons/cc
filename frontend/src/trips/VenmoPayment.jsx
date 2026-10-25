import React, { useEffect, useState } from 'react';
import { ExternalLink } from 'lucide-react';
import { Button } from './ui.jsx';
import { findMember, firstName } from './people.js';
import { money } from './money.js';
import { venmoProfile } from './venmo.js';

export function useVenmoPayment(group, onNotice) {
  const [opened, setOpened] = useState(null);
  const [returned, setReturned] = useState(false);
  const item = opened && (group.obligations?.find(o => o.id === opened.id) || (!group.obligations ? opened : null));
  const other = opened && findMember(group, opened.role === 'pay' ? opened.to_member : opened.from_member);
  const valid = Boolean(opened && item && ['open', 'replaced'].includes(item.status) && item.amount_minor === opened.amount_minor
    && (item.cycle || 0) === opened.cycle && other?.venmo_username === opened.handle);
  useEffect(() => {
    if (!opened || valid) return;
    if (item?.status === 'settled') onNotice?.(`${firstName(findMember(group, item.settled_by))} already marked it.`);
    setOpened(null); setReturned(false);
  }, [opened, valid, item, group, onNotice]);
  useEffect(() => {
    if (!opened) return;
    const returning = () => { if (document.visibilityState !== 'hidden') setReturned(true); };
    window.addEventListener('focus', returning);
    document.addEventListener('visibilitychange', returning);
    return () => { window.removeEventListener('focus', returning); document.removeEventListener('visibilitychange', returning); };
  }, [opened]);
  return { opened, pending: valid ? opened : null, item, returned: valid && returned,
    open: (obligation, role, handle) => { setOpened({ ...obligation, cycle: obligation.cycle || 0, role, handle }); setReturned(false); },
    dismiss: () => { setOpened(null); setReturned(false); } };
}

export function CheckInVenmo({ username }) {
  return <a className="cc-button cc-button--ghost trips-venmo-check" href={venmoProfile(username)} target="_blank" rel="noopener noreferrer">Check in Venmo<ExternalLink size={15} aria-hidden="true" /></a>;
}

export function PaymentPrompt({ flow, group, onSettle }) {
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  if (!flow.returned || !flow.pending) return null;
  const payment = flow.pending;
  const name = firstName(findMember(group, payment.role === 'pay' ? payment.to_member : payment.from_member));
  return <div className="trips-return-prompt" role="status">
    <strong>{payment.role === 'pay' ? `Sent ${money(payment.amount_minor, group.currency)} to ${name}?` : `Got ${money(payment.amount_minor, group.currency)} from ${name}?`}</strong>
    {flow.item.status === 'replaced' && <small>Amounts changed.</small>}
    <Button type="button" variant="primary" disabled={busy} onClick={async () => {
      setBusy(true); setError('');
      try { await onSettle(payment); flow.dismiss(); } catch (e) { setError(e.message); } finally { setBusy(false); }
    }}>{payment.role === 'pay' ? 'Sent' : 'Got it'}</Button>
    <Button type="button" variant="ghost" disabled={busy} onClick={flow.dismiss}>Not yet</Button>
    <Button type="button" variant="ghost" aria-label="Dismiss payment prompt" disabled={busy} onClick={flow.dismiss}>Dismiss</Button>
    <CheckInVenmo username={payment.handle} />
    {error && <p role="alert">{error}</p>}
  </div>;
}
