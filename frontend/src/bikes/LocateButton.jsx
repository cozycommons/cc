import React from 'react';
import { LocateFixed } from 'lucide-react';

// One locate control for every place the page needs your position. `compact` is
// the icon-only key; its accessible name stays the label.
export default function LocateButton({ geo, locate, label = 'Locate me', variant = 'secondary', compact = false }) {
  const busy = geo.status === 'locating';
  const text = busy ? 'Finding you…' : label;
  return (
    <button type="button" onClick={locate} disabled={busy} aria-label={compact ? text : undefined}
      className={`cc-button cc-button--${variant}${compact ? ' cc-button--icon' : ' cc-button--small'} bk-locate${busy ? ' cc-button--loading' : ''}`}>
      <LocateFixed size={compact ? 20 : 18} aria-hidden="true" />
      {!compact && <span>{text}</span>}
    </button>
  );
}
