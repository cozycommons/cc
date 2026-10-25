import React, { useId, useState } from 'react';

export function ConfirmationMark({ decorative = false }) {
  return <svg className="trips-venmo-confirmed" role={decorative ? undefined : 'img'} aria-label={decorative ? undefined : 'Confirmed Venmo'} aria-hidden={decorative || undefined} viewBox="0 0 24 24" width="20" height="20">
    <path fill="#1689e8" d="m12 1 3 2 3.6.4 1.1 3.4L22 10l-.8 3.5.3 3.6-3.1 1.8-2.2 2.9-3.5-.6-3.5.6-2.2-2.9-3.1-1.8.3-3.6L2 10l2.3-3.2 1.1-3.4L9 3z" />
    <path fill="none" stroke="white" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round" d="m7.5 12 3 3 6-6" />
  </svg>;
}

export default function ConfirmedVenmo({ name }) {
  const [open, setOpen] = useState(false);
  const id = useId();
  return <span className="trips-confirmation-info" onMouseEnter={() => setOpen(true)} onMouseLeave={() => setOpen(false)}>
    <button type="button" className="trips-confirmation-trigger" aria-label="About confirmed Venmo" aria-expanded={open} aria-describedby={open ? id : undefined}
      onFocus={() => setOpen(true)} onBlur={() => setOpen(false)} onClick={() => setOpen(true)} onKeyDown={e => { if (e.key === 'Escape') setOpen(false); }}><ConfirmationMark /></button>
    {open && <span id={id} role="tooltip" className="trips-confirmation-tooltip">{name?.split(/\s+/)[0] || 'This person'} confirmed this is their Venmo.</span>}
  </span>;
}
