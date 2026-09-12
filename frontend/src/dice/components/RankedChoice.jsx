import React, { useId, useRef } from 'react';

export default function RankedChoice({ ranked, onChange, disabled = false, label = 'Match type' }) {
  const groupName = useId();
  const radioRefs = { true: useRef(null), false: useRef(null) };

  const moveWithArrow = (event) => {
    const nextValue = {
      ArrowLeft: true,
      ArrowUp: true,
      ArrowRight: false,
      ArrowDown: false,
    }[event.key];
    if (nextValue === undefined) return;
    event.preventDefault();
    onChange(nextValue);
    requestAnimationFrame(() => radioRefs[String(nextValue)].current?.focus());
  };

  return (
    <fieldset className="min-w-0" disabled={disabled}>
      <legend className="jk-label mb-2">{label}</legend>
      <div
        className="relative grid grid-cols-2 rounded-xl p-1"
        role="radiogroup"
        aria-label={label}
        style={{ background: 'var(--surface-sunken)' }}
      >
        <span
          aria-hidden="true"
          className={`absolute inset-y-1 left-1 w-[calc(50%-0.375rem)] rounded-lg transition-transform duration-200 ${ranked ? '' : 'translate-x-[calc(100%+0.25rem)]'}`}
          style={{ background: 'var(--surface-card)', boxShadow: '0 1px 3px rgb(0 0 0 / 0.12)' }}
        />
        {[
          { value: true, title: 'Ranked', detail: 'Affects ELO' },
          { value: false, title: 'Unranked', detail: 'Casual game' },
        ].map((option) => {
          const selected = ranked === option.value;
          return (
            <label
              key={option.title}
              className="relative z-10 min-h-14 rounded-lg px-3 py-2 text-center grid place-content-center focus-within:ring-2 focus-within:ring-offset-1"
              style={{ color: selected ? 'var(--text-primary)' : 'var(--text-tertiary)' }}
            >
              <input
                ref={radioRefs[String(option.value)]}
                type="radio"
                name={groupName}
                checked={selected}
                disabled={disabled}
                aria-label={`${option.title} — ${option.detail}`}
                onChange={() => onChange(option.value)}
                onKeyDown={moveWithArrow}
                className="absolute inset-0 z-20 h-full w-full cursor-pointer opacity-0 disabled:cursor-not-allowed"
              />
              <span className="block text-sm font-semibold">{option.title}</span>
              <span className="block text-[11px] mt-0.5">{option.detail}</span>
            </label>
          );
        })}
      </div>
    </fieldset>
  );
}
