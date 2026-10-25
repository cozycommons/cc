import React from 'react';

// Hand-placed pixel art: one character per pixel, '.' is transparent.
// Eyes and the floating z live in their own layers so the header can animate them.
const ART = {
  32: {
    grid: [
      '................................',
      '................................',
      '................................',
      '.............OOOOOO.............',
      '...........OOCCCCCCOO...........',
      '..........OCCCHHCCCCCOO.........',
      '.........OCCCHHCCCCCCCCOO.......',
      '........OCCCHHCCCCCCCCCCCOO.....',
      '........OCCHHCCCCCCCCCCCCCCO....',
      '.......OCCCHCCCCCCCCCOOOOCCCO...',
      '.......OCCCCCCCCCCCCCO...OCCCO..',
      '......OCCCCCCCCCCCCCCCO.OOOOOO..',
      '.....OBBBBBBBBBBBBBBBBBBOPPPPPO.',
      '.....OBBBBBBBBBBBBBBBBBBOPPPPPO.',
      '.....ObbbbbbbbbbbbbbbbbbOPPPPDO.',
      '......OOOOOOOOOOOOOOOOOOOPPDDDO.',
      '......OFFFFFFFFFFFFFFFFFOOOOOO..',
      '......OFFFFFFFFFFFFFFFFFO.......',
      '......OFFFFFFFFFFFFFFFFFO.......',
      '......OFFFFFFFFFFFFFFFFFO.......',
      '......OFFFFFFFFFFFFFFFFFO.......',
      '......OFFFFFFFFFFFFFFFFFO.......',
      '......OFKKFFFFOFOFFFFKKFO.......',
      '.......OFFFFFFFOFFFFFFFO........',
      '........OOFFFFFFFFFFFOO.........',
      '.....OOOOOOOOOOOOOOOOOOOOOO.....',
      '....OLLLLLLLOOOOOOOLLLLLLLLO....',
      '...OLLLLLLLLOmmmmmOLLLLLLLLLO...',
      '...OLLLLLLOFFMFMMMFFOLLLLLLLO...',
      '...OSSSSSSOFFMFMMMFFOSSSSSSSO...',
      '...OLLLLLLLOOMMMMMOOLLLLLLLLO...',
      '...OLLLLLLLLOMMMMMOLLLLLLLLLO...',
    ],
    // [x, y, width] runs in the outline colour.
    open: [[10, 20, 3], [18, 20, 3], [9, 21, 3], [19, 21, 3]],
    shut: [[9, 21, 4], [18, 21, 4]],
    z: [[1, 1, 4], [4, 2, 1], [3, 3, 1], [2, 4, 1], [1, 5, 4]],
  },
  // Favicon cut: same character redrawn for 16px, not a downscale.
  16: {
    grid: [
      '................',
      '.......OOOO.....',
      '.....OOCCCCOO...',
      '....OCHCCCCCCO..',
      '...OCHCCCCCCCCO.',
      '...OCCCCCCCOOCCO',
      '..OBBBBBBBBBOPPO',
      '..ObbbbbbbbbOPDO',
      '...OFFFFFFFFOOO.',
      '...OFFFFFFFFO...',
      '...OFFFFFFFFO...',
      '...OKFFFFFFKO...',
      '....OFFFFFFO....',
      '..OOOOOOOOOOOO..',
      '.OLLLLFMMFLLLLO.',
      '.OLLLLOMMOLLLLO.',
    ],
    open: [[5, 10, 2], [9, 10, 2]],
    shut: [[5, 10, 2], [9, 10, 2]],
    z: [[0, 0, 3], [2, 1, 1], [1, 2, 1], [0, 3, 3]],
  },
};

// Cozy-wabi tokens: espresso, clay, clay-light, butter, amber, paper-light, paper-deep, moss, moss-dark, walnut.
const LIGHT = {
  O: '#2d2422', C: '#b76845', H: '#d68b61', K: '#d68b61', B: '#f0c477', S: '#f0c477', b: '#d39155', L: '#d39155',
  P: '#f2eadb', F: '#f2eadb', D: '#d6c5a7', M: '#69755a', m: '#465243', z: '#694b36',
};
// On dark grounds the warm fills carry the silhouette; only the z needs lifting.
const DARK = { ...LIGHT, z: '#f0c477' };

const run = ([x, y, w]) => `M${x} ${y}h${w}v1h-${w}z`;

function paths(grid, palette) {
  const byFill = {};
  grid.forEach((row, y) => {
    for (let x = 0; x < row.length;) {
      const ch = row[x];
      let w = 1;
      while (row[x + w] === ch) w += 1;
      if (ch !== '.') {
        const fill = palette[ch];
        byFill[fill] = (byFill[fill] || '') + run([x, y, w]);
      }
      x += w;
    }
  });
  return Object.entries(byFill);
}

function parts(size, tone) {
  const art = ART[size <= 20 ? 16 : 32];
  const palette = tone === 'dark' ? DARK : LIGHT;
  return {
    box: art.grid.length,
    body: paths(art.grid, palette),
    open: art.open.map(run).join(''),
    shut: art.shut.map(run).join(''),
    z: art.z.map(run).join(''),
    ink: palette.O,
    zInk: palette.z,
  };
}

// Static markup for favicons and other derived icons.
export function mascotSvg({ size = 32, tone = 'light' } = {}) {
  const p = parts(size, tone);
  const body = p.body.map(([fill, d]) => `<path fill="${fill}" d="${d}"/>`).join('');
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${p.box} ${p.box}" width="${size}" height="${size}" shape-rendering="crispEdges">${body}<path fill="${p.ink}" d="${p.open}"/><path fill="${p.zInk}" d="${p.z}"/></svg>`;
}

// Sleepy nightcap mascot. `animated` adds a slow blink and drifting z.
export default function CozyMascot({ size = 32, tone = 'light', animated = false, className = '' }) {
  const p = parts(size, tone);
  const classes = ['cc-mascot', animated && 'cc-mascot--animated', className].filter(Boolean).join(' ');
  return (
    <svg className={classes} viewBox={`0 0 ${p.box} ${p.box}`} width={size} height={size} shapeRendering="crispEdges" aria-hidden="true" focusable="false">
      {p.body.map(([fill, d]) => <path key={fill} fill={fill} d={d} />)}
      <path className="cc-mascot-eyes" fill={p.ink} d={p.open} />
      {animated && <path className="cc-mascot-blink" fill={p.ink} d={p.shut} />}
      <path className="cc-mascot-z" fill={p.zInk} d={p.z} />
    </svg>
  );
}
