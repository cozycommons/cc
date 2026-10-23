import React, { createContext, useContext, useEffect, useId, useRef, useState } from 'react';
import { Check, Copy, X } from 'lucide-react';
import { memberName, personColor } from './people.js';

export const Button = ({ children, variant = 'secondary', className = '', ...props }) => <button className={`cc-button cc-button--${variant} ${className}`} {...props}>{children}</button>;
const ModalPendingContext = createContext(null);

export function Avatar({ member, size = 32, ring = false }) {
  const style = { '--person': personColor(member), width: size, height: size, fontSize: Math.round(size * 0.45) };
  const className = `trips-avatar${ring ? ' trips-avatar--ring' : ''}`;
  return member?.avatar_url
    ? <img className={className} style={style} src={member.avatar_url} alt="" loading="lazy" decoding="async" />
    : <span className={className} style={style} aria-hidden="true">{memberName(member).slice(0, 1).toUpperCase()}</span>;
}

export function AvatarStack({ members, max = 5 }) {
  return <span className="trips-avatar-stack" aria-hidden="true">
    {members.slice(0, max).map((member) => <Avatar key={member.id} member={member} size={24} ring />)}
    {members.length > max && <span className="trips-avatar trips-avatar--more">+{members.length - max}</span>}
  </span>;
}

export function CopyButton({ value, label }) {
  const [state, setState] = useState('');
  return <button type="button" className="trips-copy" aria-label={`Copy ${label}`} onClick={async () => {
    try { await navigator.clipboard.writeText(value); setState('copied'); } catch { setState('failed'); }
  }}>{state === 'copied' ? <><Check size={14} aria-hidden="true" />Copied</> : state === 'failed' ? 'Select to copy' : <><Copy size={14} aria-hidden="true" />Copy</>}</button>;
}

export function Modal({ title, onClose, children }) {
  const ref = useRef(null);
  const [pending, setPending] = useState(false);
  useEffect(() => {
    const dialog = ref.current;
    const opener = document.activeElement;
    dialog.showModal();
    dialog.querySelector('[autofocus], input:not([type=hidden]), select, textarea')?.focus();
    return () => {
      if (dialog.open) dialog.close();
      // If the opener is gone (e.g. its row was deleted), return focus to the page heading instead of <body>.
      (opener?.isConnected ? opener : document.querySelector('#trips-main h1'))?.focus?.();
    };
  }, []);
  return <dialog ref={ref} className="trips-modal" aria-labelledby="trips-modal-title" aria-busy={pending} onCancel={(event) => { event.preventDefault(); if (!pending) onClose(); }} onClick={(event) => {
    if (pending || event.target !== ref.current) return;
    const bounds = ref.current.getBoundingClientRect();
    if (event.clientX < bounds.left || event.clientX > bounds.right || event.clientY < bounds.top || event.clientY > bounds.bottom) onClose();
  }}>
    <div className="trips-modal-head"><h2 id="trips-modal-title">{title}</h2><Button variant="ghost" aria-label="Close dialog" disabled={pending} onClick={onClose}><X size={19} /></Button></div>
    <ModalPendingContext.Provider value={setPending}>{children}</ModalPendingContext.Provider>
  </dialog>;
}

// One submit at a time; the draft stays on errors; dismissal is blocked while saving.
export function Form({ onSubmit, children, submit, onCancel, destructive = false, aside = null, name }) {
  const setPending = useContext(ModalPendingContext);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const mounted = useRef(true);
  useEffect(() => { mounted.current = true; return () => { mounted.current = false; }; }, []);
  return <form className="trips-form" name={name} onSubmit={async (event) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setPending?.(true); setError('');
    try { await onSubmit(event.nativeEvent?.submitter?.value || ''); } catch (err) { if (mounted.current) setError(err.message); } finally {
      if (mounted.current) { setBusy(false); setPending?.(false); }
    }
  }}>
    <fieldset disabled={busy} className="trips-form-fields">{children}</fieldset>
    {error && <p className="trips-error" role="alert">{error}</p>}
    <div className="trips-form-actions">{aside && <fieldset className="trips-form-aside" disabled={busy}>{aside}</fieldset>}<Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>Cancel</Button><Button type="submit" variant={destructive ? 'destructive' : 'primary'} disabled={busy}>{busy ? 'Saving…' : submit}</Button></div>
  </form>;
}

export function Field({ label, children, hint }) {
  const id = useId();
  return <div className="trips-field"><label htmlFor={id}>{label}</label>{React.cloneElement(children, { id, ...(hint ? { 'aria-describedby': `${id}-hint` } : {}) })}{hint && <small id={`${id}-hint`}>{hint}</small>}</div>;
}
