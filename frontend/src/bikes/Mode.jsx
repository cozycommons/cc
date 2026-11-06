import React, { useCallback, useState } from 'react';
import { Bike, SquareParking } from 'lucide-react';

const KEY = 'cozy-bikes.need';
const NEEDS = ['bike', 'ebike', 'dock'];

export const MODES = [
  { key: 'bike', label: 'Find a bike', Icon: Bike },
  { key: 'dock', label: 'Find a dock', Icon: SquareParking },
];

export const modeOf = (need) => (need === 'dock' ? 'dock' : 'bike');

// ?need= wins (shared links), then the last choice on this device, then bike.
export function useNeed() {
  const [need, setState] = useState(() => {
    const query = new URLSearchParams(window.location.search).get('need');
    if (NEEDS.includes(query)) return query;
    try {
      const saved = window.localStorage.getItem(KEY);
      if (NEEDS.includes(saved)) return saved;
    } catch { /* storage blocked: use the default */ }
    return 'bike';
  });
  const setNeed = useCallback((next) => {
    setState(next);
    try { window.localStorage.setItem(KEY, next); } catch { /* storage blocked: still works this visit */ }
  }, []);
  return [need, setNeed];
}

// The one choice that changes every answer: renting a bike or returning one.
export default function ModeSwitch({ need, setNeed, onPick, large = false }) {
  const mode = modeOf(need);
  const pick = (key) => {
    setNeed(key === 'dock' ? 'dock' : need === 'ebike' ? 'ebike' : 'bike');
    onPick?.(key);
  };
  return (
    <div className={`bk-mode${large ? ' bk-mode--large' : ''}`}>
      <div className="bk-mode__choices" role="radiogroup" aria-label="I need">
        {MODES.map(({ key, label, Icon }) => (
          <button key={key} type="button" role="radio" aria-checked={mode === key}
            className={`bk-mode__choice bk-mode__choice--${key}`} onClick={() => pick(key)}>
            <Icon size={large ? 30 : 22} aria-hidden="true" />
            <span>{label}</span>
          </button>
        ))}
      </div>
      {mode === 'bike' && !large && (
        <label className="bk-check bk-mode__ebike">
          <input type="checkbox" checked={need === 'ebike'} onChange={(e) => setNeed(e.target.checked ? 'ebike' : 'bike')} />
          E-bikes only
        </label>
      )}
    </div>
  );
}
