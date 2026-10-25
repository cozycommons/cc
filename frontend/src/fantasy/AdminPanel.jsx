import React, { useEffect, useRef } from 'react';
import './AdminPanel.css';

const seasonOption = entry => (typeof entry === 'object' ? entry : { value: entry, label: String(entry) });

// Quiet icon in the site header that opens the admin settings; render it for admins only.
export const AdminEntry = React.forwardRef(function AdminEntry({ open, onClick, controls = 'fx-admin-panel' }, ref) {
  return (
    <button ref={ref} type="button" className="cc-sitebar-icon fx-admin-entry" aria-label="Admin" title="Admin"
      aria-expanded={!!open} aria-controls={open ? controls : undefined} onClick={onClick}>
      <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true">
        <path d="M3 6h9M15 6h2M3 14h2M8 14h9" />
        <circle cx="13.5" cy="6" r="1.8" /><circle cx="6.5" cy="14" r="1.8" />
      </svg>
    </button>
  );
});

// Admin settings: presentational only. The parent owns data, auth, and saving.
// `children` renders extra <fieldset className="fx-admin-group"> sections below League.
export default function AdminPanel({
  id = 'fx-admin-panel',
  season, onSeasonChange, seasons,
  leagueId, onLeagueIdChange,
  onSave, onClose,
  loading = false, saving = false,
  status, error, leagueUrl,
  children,
}) {
  const headingRef = useRef(null);
  useEffect(() => { headingRef.current?.focus(); }, []);
  const busy = loading || saving;
  const message = loading ? 'Loading…' : saving ? 'Saving…' : status === 'saved' ? 'Saved' : status || '';

  return (
    <section id={id} className="fx-admin" aria-labelledby={`${id}-title`} aria-busy={busy}
      onKeyDown={event => { if (event.key === 'Escape' && onClose) onClose(); }}>
      <div className="fx-admin-head">
        <h2 id={`${id}-title`} ref={headingRef} tabIndex={-1}>Admin</h2>
        {onClose && (
          <button type="button" className="fx-admin-close" onClick={onClose} aria-label="Close admin">
            <svg viewBox="0 0 20 20" width="18" height="18" aria-hidden="true"><path d="M5 5l10 10M15 5L5 15" /></svg>
          </button>
        )}
      </div>
      <form onSubmit={event => { event.preventDefault(); if (!busy) onSave?.(); }}>
        <fieldset className="fx-admin-group" disabled={busy}>
          <legend>League</legend>
          <div className="fx-admin-fields">
            <label className="fx-admin-field fx-admin-field--season">
              <span>Season</span>
              {seasons?.length ? (
                <select value={season ?? ''} onChange={event => onSeasonChange?.(event.target.value)}>
                  {seasons.map(seasonOption).map(option => (
                    <option key={option.value} value={option.value}>{option.label}</option>
                  ))}
                </select>
              ) : (
                <input type="text" inputMode="numeric" pattern="[0-9]{4}" maxLength={4} autoComplete="off"
                  value={season ?? ''} onChange={event => onSeasonChange?.(event.target.value)} />
              )}
            </label>
            <label className="fx-admin-field fx-admin-field--league">
              <span>ESPN league ID</span>
              <input type="text" inputMode="numeric" pattern="[0-9]{1,12}" maxLength={12} required autoComplete="off" spellCheck={false}
                value={leagueId ?? ''} onChange={event => onLeagueIdChange?.(event.target.value)}
                aria-invalid={error ? true : undefined} aria-describedby={error ? `${id}-error` : undefined} />
            </label>
          </div>
          <div className="fx-admin-actions">
            <button type="submit" className="cc-button cc-button--primary fx-admin-save" disabled={busy}>{saving ? 'Saving…' : 'Save'}</button>
            {leagueUrl && (
              <a className="cc-button cc-button--ghost fx-admin-open" href={leagueUrl} target="_blank" rel="noopener noreferrer">
                <span className="fx-espn-badge" aria-hidden="true">ESPN</span>
                Open league
                <svg viewBox="0 0 20 20" width="14" height="14" aria-hidden="true"><path d="M8 4h8v8M16 4L6 14" /></svg>
              </a>
            )}
          </div>
        </fieldset>
        {children}
        <p className={`fx-admin-status${message && !busy && status === 'saved' ? ' fx-admin-status--ok' : ''}`}
          role="status" aria-live="polite">{error ? '' : message}</p>
        {error && <p id={`${id}-error`} className="fx-admin-error" role="alert">{error}</p>}
      </form>
    </section>
  );
}
