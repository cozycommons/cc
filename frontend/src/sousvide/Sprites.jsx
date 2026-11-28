import React from 'react';

// Pixel sprites drawn as SVG: each one is a grid of letters, one per pixel, and a
// palette. Every sprite is turned into one path per colour once, at load, so a
// render costs a few <path> elements and no canvas.
const PAL = {
  o: '#2b1d1a', // outline
  r: '#c4344a', // meat
  p: '#e07a83', // pink cut face
  f: '#f6e6cc', // fat
  b: '#efe3c4', // bone
  w: '#ffffff',
  c: '#7a3f1f', // crust
  t: '#f2eadb', // twine
  s: '#a9b4b8', // steel
  d: '#5f8fb8', // deep water or ice shadow
  i: '#bfe6f5', // ice
  v: '#d9d2c4', // steam
  y: '#ffc531', // gold
  a: '#f2662a', // lava orange
  k: '#3d2f29', // ink
  l: '#3fa1e0', // card blue
  n: '#f0b48c', // skin
  m: '#c98a64', // skin crease
  g: '#58b72a', // grass
};

const ART = {
  ribeye: [
    '...oooooooooo...',
    '..offffffffffo..',
    '.offrrrrrrrrffo.',
    'offrrrrfffrrrrfo',
    'ofrrrrffrffrrrfo',
    'ofrrrrfrrrfrrrfo',
    'ofrrrrrfffrrrrfo',
    'offrrrrrrrrrrffo',
    '.offrrrrrrrrffo.',
    '..offffffffffo..',
    '...oooooooooo...',
  ],
  'ribeye-bone': [
    '...oooooooooo...',
    '..obbbfffffffo..',
    '.obwbfrrrrrrffo.',
    'obwbrrrfffrrrrfo',
    'obwbrrffrffrrrfo',
    'obwbrrfrrrfrrrfo',
    'obwbrrrfffrrrrfo',
    'obwbrrrrrrrrrffo',
    '.obwbrrrrrrrffo.',
    '..obbbfffffffo..',
    '...oooooooooo...',
  ],
  strip: [
    '.oooooooooooooo.',
    'offffffffffffffo',
    'offffffffffffffo',
    'orrrrrrrrrrrrrro',
    'orrrrrfrrrrrrrro',
    'orrrrrrrrrrfrrro',
    'orrrrrrrrrrrrrro',
    'orrfrrrrrrrrrrro',
    'orrrrrrrrrrrrrro',
    '.orrrrrrrrrrrro.',
    '..oooooooooooo..',
  ],
  filet: [
    '....oooooooo....',
    '..oorrrrrrrroo..',
    '.orrrrrrrrrrrro.',
    '.orrrrprrrrrrro.',
    'orrrrrrrrrrrrrro',
    'orrrrrrrrrprrrro',
    'orrrrrrrrrrrrrro',
    '.orrprrrrrrrrro.',
    '.orrrrrrrrrrrro.',
    '..oorrrrrrrroo..',
    '....oooooooo....',
  ],
  roast: [
    '................',
    '..ooooooooooooo.',
    '.orrtrrrtrrrtrro',
    'orrrtrrrtrrrtrpo',
    'orrrtrrrtrrrtrpo',
    'orrrtrrrtrrrtrpo',
    'orrrtrrrtrrrtrpo',
    '.orrtrrrtrrrtrro',
    '..ooooooooooooo.',
    '................',
    '................',
  ],
  pot: [
    '...v..v..v..',
    '..v..v..v...',
    '............',
    'oooooooooooo',
    '.osssssssso.',
    '.oddddddddo.',
    '.oddddddddo.',
    '.oddrrrrddo.',
    '.oddddddddo.',
    '.osssssssso.',
    '..oooooooo..',
    '............',
  ],
  flame: [
    '......o.....',
    '.....oyo....',
    '.....oyyo...',
    '....oyyyo...',
    '...oyyayyo..',
    '..oyyaaayo..',
    '..oyaaraayo.',
    '.oyaarrraayo',
    '.oyarrrrrayo',
    '.oyarrrrrayo',
    '..oyaaaaayo.',
    '...ooooooo..',
  ],
  ice: [
    '............',
    '.oooooooooo.',
    '.owwiiiiiio.',
    '.owiiiiiiio.',
    '.oiiiiiiiio.',
    '.oiiiiiiiio.',
    '.oiiiiiiido.',
    '.oiiiiiiddo.',
    '.oiiiiidddo.',
    '.oooooooooo.',
    '............',
    '............',
  ],
  thermo: [
    '..........o.',
    '.........oso',
    '........oso.',
    '.......oso..',
    '......oso...',
    '.....oso....',
    '..ooooso....',
    '.oyyyyo.....',
    'oyykkyyo....',
    'oyykyyyo....',
    'oyyyyyyo....',
    '.oooooo.....',
  ],
  finger: [
    '..ooooooooooo.',
    '.onnnnnnnnnnto',
    'onnnnnnnnnntto',
    'onnnmnnnnnnnto',
    '.onnnnnnnnnnoo',
    '..ooooooooooo.',
  ],
  bell: [
    '...oo...',
    '..oyyo..',
    '.oyyyyo.',
    '.oyyyyo.',
    '.oyyyyo.',
    'oyyyyyyo',
    'oooooooo',
    '...oo...',
  ],
  star: [
    '...o...',
    '..oyo..',
    'ooyyyoo',
    'oyyyyyo',
    '.oyyyo.',
    'oyyoyyo',
    'oo...oo',
  ],
};

function build(rows) {
  const runs = {};
  rows.forEach((row, y) => {
    let x = 0;
    while (x < row.length) {
      const ch = row[x];
      let n = 1;
      while (row[x + n] === ch) n += 1;
      if (PAL[ch]) (runs[ch] ??= []).push(`M${x} ${y}h${n}v1h-${n}z`);
      x += n;
    }
  });
  return { w: Math.max(...rows.map((r) => r.length)), h: rows.length, parts: Object.entries(runs).map(([ch, d]) => [PAL[ch], d.join('')]) };
}
export const SPRITES = Object.fromEntries(Object.entries(ART).map(([k, rows]) => [k, build(rows)]));

// One sprite at `scale` screen pixels per art pixel. Decorative: the control
// around it carries the name.
export function Sprite({ name, scale = 3, className = '' }) {
  const s = SPRITES[name];
  return (
    <svg className={`sv-sprite ${className}`} viewBox={`0 0 ${s.w} ${s.h}`} width={s.w * scale} height={s.h * scale}
      shapeRendering="crispEdges" aria-hidden="true" focusable="false">
      {s.parts.map(([fill, d]) => <path key={fill} fill={fill} d={d} />)}
    </svg>
  );
}

// A one-shot pixel burst. It plays once when it mounts, so a caller restarts it by
// changing its key; it is absolutely placed and never moves the layout.
const SPARKS = Array.from({ length: 14 }, (_, i) => {
  const a = (i / 14) * Math.PI * 2;
  const r = i % 2 ? 46 : 70;
  return { dx: Math.round(Math.cos(a) * r), dy: Math.round(Math.sin(a) * r), c: ['#ffc531', '#58b72a', '#f2662a', '#3fa1e0'][i % 4], d: (i % 3) * 40 };
});
export function Burst({ className = '' }) {
  return (
    <span className={`sv-burst ${className}`} aria-hidden="true">
      {SPARKS.map((s, i) => (
        <i key={i} style={{ '--dx': `${s.dx}px`, '--dy': `${s.dy}px`, '--c': s.c, animationDelay: `${s.d}ms` }} />
      ))}
    </span>
  );
}
