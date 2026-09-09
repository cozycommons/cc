import Phaser from 'phaser';
import { createCommonsPhaserGame } from '../commons-phaser.js';
import { getCommonsRenderMetadata } from '../commons-assets.js';
import { supportDepthOffset } from '../render/grounding.js';

if (!import.meta.env.DEV) throw new Error('Commons review is available only in development');

const perimeter = [
  [6, 6], [7, 6], [8, 6], [9, 6], [10, 6],
  [10, 7], [10, 8], [10, 9], [10, 10],
  [9, 10], [8, 10], [7, 10], [6, 10],
  [6, 9], [6, 8], [6, 7],
];
const params = new URLSearchParams(window.location.search);
const requestedStep = Number(params.get('step') || 0);
let cursor = Number.isInteger(requestedStep) ? ((requestedStep % perimeter.length) + perimeter.length) % perimeter.length : 0;
let version = 1;
let reversed = false;
const propInput = document.querySelector('#prop');
const orientationInput = document.querySelector('#orientation');
const position = document.querySelector('#position');
if ([...propInput.options].some((option) => option.value === params.get('prop'))) propInput.value = params.get('prop');
if (params.get('orientation') === 'north') orientationInput.value = 'north';

function snapshot() {
  const [tile_x, tile_y] = perimeter[cursor];
  const prop = propInput.value;
  const entries = [
    ['rug', { id: 'rug', asset: 'area-rug', tile_x: 8, tile_y: 8 }],
    ['prop', { id: 'prop', asset: prop, tile_x: 8, tile_y: 8, orientation: orientationInput.value }],
  ];
  if (prop === 'area-rug') entries.pop();
  if (reversed) entries.reverse();
  const metadata = getCommonsRenderMetadata(prop, orientationInput.value);
  const propDepth = metadata.floorDecoration ? 'floor pass' : (160 + supportDepthOffset(metadata)).toFixed(1);
  position.textContent = `Resident (${tile_x}, ${tile_y}) · depth ${10 * (tile_x + tile_y)}; furniture (8, 8) · depth ${propDepth}`;
  return {
    id: 'commons-review', version, layout_version: 9, server_time_ms: Date.now(),
    state: {
      schema_version: 7, catalog_version: 'commons-v2',
      objects: Object.fromEntries(entries),
      actors: { host: { id: 'host', asset: 'host', tile_x, tile_y, view: 'front_right' } },
      ambient: { enabled: false, revision: 1, reason: 'resting_only' },
    },
  };
}

const game = createCommonsPhaserGame({
  Phaser, parent: document.querySelector('#room'), initialScene: snapshot(),
  motionPolicy: { reducedMotion: true, animate: false },
});
function refresh() { version += 1; game.syncState(snapshot()); }
document.querySelector('#previous').addEventListener('click', () => {
  cursor = (cursor + perimeter.length - 1) % perimeter.length;
  refresh();
});
document.querySelector('#next').addEventListener('click', () => {
  cursor = (cursor + 1) % perimeter.length;
  refresh();
});
document.querySelector('#shuffle').addEventListener('click', () => { reversed = !reversed; refresh(); });
propInput.addEventListener('change', refresh);
orientationInput.addEventListener('change', refresh);
if (import.meta.hot) import.meta.hot.dispose(() => game.destroy(true));
