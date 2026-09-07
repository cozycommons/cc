import React from 'react';
import { Input } from '@/components/ui/input';

// Both sinks and self sinks are rare enough per player that this defaults to
// a quiet "none" chip and only reveals a number input once the user says
// otherwise.
export default function SinkCountInput({ name, statLabel, value, onChange }) {
  const hasAny = value > 0;

  if (!hasAny) {
    return (
      <button
        type="button"
        onClick={() => onChange(1)}
        className="text-left"
        style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-tertiary)' }}
      >
        {name}: no {statLabel} · <span style={{ textDecoration: 'underline' }}>add some</span>
      </button>
    );
  }

  return (
    <div className="flex items-center gap-2">
      <span style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-tertiary)' }}>
        {name} {statLabel}:
      </span>
      <Input
        type="number"
        min={0}
        value={value}
        onChange={(e) => onChange(Math.max(0, parseInt(e.target.value, 10) || 0))}
        className="w-16 h-7"
      />
      <button
        type="button"
        onClick={() => onChange(0)}
        style={{ fontFamily: 'var(--font-mono)', fontSize: 11, color: 'var(--text-tertiary)' }}
      >
        clear
      </button>
    </div>
  );
}
