import React from 'react';
import '../../../../design/cozy-wabi/data-patterns.css';

export function SegmentedControl({ label, options, value, onChange }) {
  const name = React.useId();
  const selected = Math.max(0, options.findIndex(option => option.value === value));
  return <fieldset className="cc-picker">
    <legend className="cc-label">{label}</legend>
    <div className="cc-picker__track" style={{ '--segments': options.length, '--selected': selected }}>
      <span className="cc-picker__indicator" aria-hidden="true" />
      {options.map(option => <label className="cc-picker__option" key={option.value}>
        <input type="radio" name={name} value={option.value} checked={value === option.value} onChange={() => onChange(option.value)} />
        <span>{option.label}</span>
      </label>)}
    </div>
  </fieldset>;
}

export function DataRow({ title, subtitle, value, children }) {
  return <details className="cc-data-row">
    <summary><span className="cc-data-row__name"><strong>{title}</strong>{subtitle && <small>{subtitle}</small>}</span><span className="cc-data-row__value">{value}</span><span className="cc-data-row__chevron" aria-hidden="true">↗</span></summary>
    <div className="cc-data-row__detail">{children}</div>
  </details>;
}

export function ComparisonBar({ label, value, total, leftLabel, rightLabel }) {
  const share = total > 0 ? Math.min(100, Math.max(0, value / total * 100)) : 0;
  return <div className="cc-comparison" role="group" aria-label={label}>
    <div className="cc-comparison__labels"><span>{leftLabel}</span><span>{rightLabel}</span></div>
    <div className="cc-comparison__track" aria-hidden="true"><span style={{ width: `${share}%` }} /></div>
  </div>;
}

export function Skeleton({ label = 'Loading' }) {
  return <div className="cc-skeleton" role="status"><span className="cc-sr-only">{label}</span><div aria-hidden="true"><i /><i /><i /></div></div>;
}
