import React, {useState} from 'react';
import {render, screen, fireEvent, cleanup, act} from '@testing-library/react';
import {afterEach, it, expect, vi} from 'vitest';
import Controls, {keyLabel, buttonLabel} from './Controls';

const actions = [{id: 'left', name: 'Move left', game_key: 'ArrowLeft'}, {id: 'right', name: 'Move right', game_key: 'ArrowRight'},
  {id: 'cw', name: 'Rotate right', game_key: 'KeyX'}];
let latest;
function Harness({initial}) {
  const [binding, setBinding] = useState(initial);
  latest = binding;
  return <Controls actions={actions} binding={binding} onChange={setBinding}/>;
}
afterEach(() => { cleanup(); vi.unstubAllGlobals(); });

it('labels keys and standard gamepad buttons', () => {
  expect(keyLabel('ArrowLeft')).toBe('←');
  expect(keyLabel('KeyJ')).toBe('J');
  expect(keyLabel('ShiftLeft')).toBe('Shift');
  expect(buttonLabel(14)).toBe('D-pad ←');
  expect(buttonLabel(undefined)).toBe('—');
});

it('binds a clicked action to the next key and moves it off another action', () => {
  render(<Harness initial={{keys: {left: 'KeyJ', right: 'KeyL'}, pad: {}}}/>);
  fireEvent.click(screen.getByRole('button', {name: 'Extra key for Move right'}));
  expect(screen.getByRole('button', {name: 'Extra key for Move right'})).toHaveTextContent('Press a key…');
  fireEvent.keyDown(window, {code: 'KeyJ'});
  expect(latest.keys).toEqual({right: 'KeyJ'});
  expect(screen.getByLabelText('Keyboard preset').value).toBe('custom');
});

it('refuses a key the game already uses and clears with Escape', () => {
  render(<Harness initial={{keys: {left: 'KeyJ'}, pad: {}}}/>);
  fireEvent.click(screen.getByRole('button', {name: 'Extra key for Move left'}));
  fireEvent.keyDown(window, {code: 'KeyX'});
  expect(screen.getByRole('status')).toHaveTextContent("X is already the game's key for Rotate right.");
  expect(latest.keys).toEqual({left: 'KeyJ'});
  fireEvent.click(screen.getByRole('button', {name: 'Extra key for Move left'}));
  fireEvent.keyDown(window, {code: 'Escape'});
  expect(latest.keys).toEqual({});
});

it('binds the first gamepad button pressed after listening starts', async () => {
  const buttons = Array.from({length: 17}, () => ({pressed: false}));
  buttons[0].pressed = true; // held before listening: ignored
  const pad = {index: 0, connected: true, buttons, axes: [0, 0]};
  vi.stubGlobal('navigator', {...navigator, getGamepads: () => [pad]});
  let tick;
  vi.stubGlobal('requestAnimationFrame', callback => { tick = callback; return 1; });
  vi.stubGlobal('cancelAnimationFrame', () => {});
  render(<Harness initial={{keys: {}, pad: {left: 14, right: 15}}}/>);
  fireEvent.click(screen.getByRole('button', {name: 'Gamepad button for Move left'}));
  act(() => tick());
  expect(latest.pad.left).toBe(14);
  buttons[15].pressed = true;
  act(() => tick());
  expect(latest.pad).toEqual({left: 15});
  expect(screen.getByRole('button', {name: 'Gamepad button for Move left'})).toHaveTextContent('D-pad →');
});
