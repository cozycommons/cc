import React, { createContext, useContext, useEffect, useId, useRef, useState } from 'react';
import { X } from 'lucide-react';

export const Button = ({ children, variant = 'secondary', className = '', ...props }) => <button className={`cc-button cc-button--${variant} ${className}`} {...props}>{children}</button>;
const ModalPendingContext = createContext(null);

export function Modal({ title, onClose, children }) {
  const ref = useRef(null);
  const [pending, setPending] = useState(false);
  useEffect(() => {
    const dialog = ref.current;
    dialog.showModal();
    dialog.querySelector('input, select, textarea')?.focus();
    return () => { if (dialog.open) dialog.close(); };
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

export function Form({ onSubmit, children, submit, onCancel, destructive = false }) {
  const setPending = useContext(ModalPendingContext);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  return <form className="trips-form" onSubmit={async (event) => {
    event.preventDefault();
    if (busy) return;
    setBusy(true); setPending?.(true); setError('');
    try { await onSubmit(); } catch (err) { setError(err.message); } finally { setBusy(false); setPending?.(false); }
  }}>
    <fieldset disabled={busy} className="trips-form-fields">{children}</fieldset>
    {error && <p className="trips-error" role="alert">{error}</p>}
    <div className="trips-form-actions"><Button type="button" variant="ghost" onClick={onCancel} disabled={busy}>Cancel</Button><Button variant={destructive ? 'destructive' : 'primary'} disabled={busy}>{busy ? 'Saving…' : submit}</Button></div>
  </form>;
}

export function Field({ label, children, hint }) {
  const id = useId();
  return <div className="trips-field"><label htmlFor={id}>{label}</label>{React.cloneElement(children, { id, ...(hint ? { 'aria-describedby': `${id}-hint` } : {}) })}{hint && <small id={`${id}-hint`}>{hint}</small>}</div>;
}
