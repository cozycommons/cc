import {readFileSync} from 'node:fs';
import {resolve} from 'node:path';
import {it, expect, vi} from 'vitest';

// The player frame script is served by the backend; run it here against a stub player.
const source = readFileSync(resolve(process.cwd(), '../backend/arcade/frame.js'), 'utf8')
  .replace('__PARENT_ORIGINS__', JSON.stringify(['http://localhost:8080']));

it('turns a held gamepad button into the game key inside the player', async () => {
  document.body.innerHTML = '<div id="game"></div><p id="status"></p>';
  const host = document.createElement('div');
  const inner = document.createElement('div');
  inner.tabIndex = 0;
  host.attachShadow({mode: 'open'}).append(inner);
  const loaded = vi.fn(async () => {});
  window.RufflePlayer = {newest: () => ({createPlayer: () => Object.assign(host, {ruffle: () => ({load: loaded})})})};
  const buttons = Array.from({length: 17}, () => ({pressed: false}));
  const pad = {index: 0, connected: true, buttons, axes: [0, 0]};
  vi.stubGlobal('navigator', {...navigator, getGamepads: () => [pad]});
  let tick = () => {};
  vi.stubGlobal('requestAnimationFrame', callback => { tick = callback; return 1; });
  new Function(source)();
  const launch = {entry: 'game.swf', session: 's', origins: {}, callbacks: {},
    input: {targets: {left: {code: 'ArrowLeft', key: 'ArrowLeft', key_code: 37}}, keys: {KeyJ: 'left'}, buttons: {14: 'left'}}};
  window.dispatchEvent(new MessageEvent('message', {source: window, origin: 'http://localhost:8080',
    data: {type: 'arcade-launch', launch, settings: {sound: false}}}));
  await vi.waitFor(() => expect(loaded).toHaveBeenCalled());
  inner.focus();
  const seen = [];
  for (const type of ['keydown', 'keyup']) inner.addEventListener(type, event => seen.push([type, event.key, event.keyCode, event.which]));
  buttons[14].pressed = true; tick(); tick();
  pad.axes[0] = -1; tick(); // the stick on the same action does not press it twice
  buttons[14].pressed = false; pad.axes[0] = 0; tick();
  expect(seen).toEqual([['keydown', 'ArrowLeft', 37, 37], ['keyup', 'ArrowLeft', 37, 37]]);
  vi.unstubAllGlobals();
});
