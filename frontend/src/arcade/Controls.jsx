import React, {useEffect, useRef, useState} from 'react';

// Extra inputs only: the game's own keys always keep working.
export const PRESETS = {
  arrows: {label: 'Arrows', keys: {}},
  hhkb: {label: 'HHKB · J / K / L', keys: {left: 'KeyJ', right: 'KeyL', soft: 'KeyK'}},
  wasd: {label: 'WASD', keys: {left: 'KeyA', right: 'KeyD', soft: 'KeyS', hard: 'KeyW'}},
};
const ARROWS = {ArrowLeft: '←', ArrowRight: '→', ArrowUp: '↑', ArrowDown: '↓'};
const PUNCTUATION = {Semicolon: ';', Equal: '=', Comma: ',', Minus: '-', Period: '.', Slash: '/', Backquote: '`',
  BracketLeft: '[', Backslash: '\\', BracketRight: ']', Quote: "'"};
// Standard gamepad layout names.
const BUTTONS = ['A', 'B', 'X', 'Y', 'LB', 'RB', 'LT', 'RT', 'Back', 'Start', 'L3', 'R3',
  'D-pad ↑', 'D-pad ↓', 'D-pad ←', 'D-pad →', 'Home'];

export function keyLabel(code) {
  if (!code) return '—';
  if (ARROWS[code]) return ARROWS[code];
  if (/^Key[A-Z]$/.test(code)) return code.slice(3);
  if (/^(Digit|Numpad)\d$/.test(code)) return code.slice(-1);
  return PUNCTUATION[code] ?? code.replace(/^(Shift|Control|Alt|Meta)(Left|Right)$/, '$1');
}
export const buttonLabel = button => button == null ? '—' : BUTTONS[button] ?? 'Button ' + button;

function presetOf(keys) {
  const same = (a, b) => Object.keys(a).length === Object.keys(b).length && Object.entries(a).every(([k, v]) => b[k] === v);
  return Object.keys(PRESETS).find(name => same(PRESETS[name].keys, keys)) ?? 'custom';
}

/** Click-to-bind table for one game's extra keys and gamepad buttons. */
export default function Controls({actions, binding, onChange}) {
  const [listening, setListening] = useState(null); // {action, kind: 'keys' | 'pad'}
  const [note, setNote] = useState('');
  const latest = useRef(binding);
  latest.current = binding;
  const gameKeys = Object.fromEntries(actions.map(action => [action.game_key, action]));

  function bind(kind, action, value) {
    const current = {...latest.current[kind]};
    for (const [other, bound] of Object.entries(current)) if (bound === value) delete current[other];
    if (value == null) delete current[action]; else current[action] = value;
    onChange({...latest.current, [kind]: current});
  }
  useEffect(() => {
    if (listening?.kind !== 'keys') return;
    const receive = event => {
      event.preventDefault(); event.stopImmediatePropagation();
      const {action} = listening;
      setListening(null);
      if (event.code === 'Escape') return bind('keys', action, null);
      const owner = gameKeys[event.code];
      if (owner) return setNote(`${keyLabel(event.code)} is already the game's key for ${owner.name}.`);
      bind('keys', action, event.code);
    };
    addEventListener('keydown', receive, true);
    return () => removeEventListener('keydown', receive, true);
  }, [listening]);
  useEffect(() => {
    if (listening?.kind !== 'pad') return;
    const cancel = event => {
      if (event.code !== 'Escape') return;
      event.preventDefault(); setListening(null); bind('pad', listening.action, null);
    };
    // Bind the first button that goes down after listening starts.
    const pads = () => [...(navigator.getGamepads?.() ?? [])].filter(Boolean);
    const before = new Set(pads().flatMap(pad => pad.buttons.flatMap((b, i) => b.pressed ? [pad.index + ':' + i] : [])));
    let frame;
    const poll = () => {
      for (const pad of pads()) {
        const button = pad.buttons.findIndex((b, i) => b.pressed && !before.has(pad.index + ':' + i));
        if (button >= 0) { setListening(null); bind('pad', listening.action, button); return; }
        pad.buttons.forEach((b, i) => { if (!b.pressed) before.delete(pad.index + ':' + i); });
      }
      frame = requestAnimationFrame(poll);
    };
    frame = requestAnimationFrame(poll);
    addEventListener('keydown', cancel, true);
    return () => { cancelAnimationFrame(frame); removeEventListener('keydown', cancel, true); };
  }, [listening]);

  const start = (action, kind) => {
    setNote('');
    setListening(listening?.action === action && listening.kind === kind ? null : {action, kind});
  };
  const preset = presetOf(binding.keys);
  return <section className="arcade-controls" aria-label="Controls">
    <label>Keyboard preset <select value={preset} onChange={event => {
      if (PRESETS[event.target.value]) onChange({...binding, keys: {...PRESETS[event.target.value].keys}});
    }}>
      {Object.entries(PRESETS).map(([name, value]) => <option key={name} value={name}>{value.label}</option>)}
      {preset === 'custom' && <option value="custom">Custom</option>}
    </select></label>
    <table>
      <thead><tr><th>Action</th><th>Game key</th><th>Extra key</th><th>Gamepad</th></tr></thead>
      <tbody>{actions.map(({id, name, game_key}) => <tr key={id}>
        <th scope="row">{name}</th>
        <td><kbd>{keyLabel(game_key)}</kbd></td>
        {['keys', 'pad'].map(kind => {
          const active = listening?.action === id && listening.kind === kind;
          const value = binding[kind][id];
          return <td key={kind}><button type="button" className={active ? 'listening' : undefined}
            aria-label={`${kind === 'keys' ? 'Extra key' : 'Gamepad button'} for ${name}`}
            onClick={() => start(id, kind)}>
            {active ? (kind === 'keys' ? 'Press a key…' : 'Press a button…') : kind === 'keys' ? keyLabel(value) : buttonLabel(value)}
          </button></td>;
        })}
      </tr>)}</tbody>
    </table>
    <p role="status">{note || (listening ? 'Esc clears this binding.' : '')}</p>
  </section>;
}
