import React from 'react';

// Hand-placed pixel art: one character per pixel, '.' is transparent, 'z' is the floating z.
// Colours paint in PALETTE order, outlines first, so a run may pass under pixels painted later.
const ART = {
  32: {
    grid: [
      '................................',
      'zzzz............................',
      '...z........AAAAAA..............',
      '..z.......aaDEEDCCCAAA..........',
      '.z.......aDEEDDCCCCCCCAA........',
      'zzzz....aDEDDCCCCCCCCCCCAA......',
      '.......aDDDCCCCCCCCCaaCCCCA.....',
      '.......aDDCCCCCCCCCCCCaaCCCA....',
      '......aDDCCCCCCCCCCCCCCaaCCA....',
      '.....hyyyyyyyyYYYYYYYYYhaaAhhhh.',
      '.....hYYYYYYYcccYYYYYYGhaAhQQPPh',
      '....hjjjjjjjjjjjjjjjjjjjJ.hQPPPh',
      '...hhHGGHhhhhhhhhhhhHhhhhJhPPPph',
      '...hHHHHhhjhhhhhhhjhhhhhhJhPPpph',
      '...JHhhjsssssjhjsssssjhhhJ.hhhh.',
      '...JHhjsssssssjsssssssjhhJ......',
      '...JHjssttttssssstttttstjhJ.....',
      '...JHjseeeeesssssseeeeetjhJ.....',
      '...JHjsshQhhssssshQhhstjhJ......',
      '....JVssrrssssTssssrrttVJ.......',
      '......TtscssssssssscstT.........',
      '.......TTTTTTTuTTTTTTT..........',
      '........hmgggggggggnh...........',
      '.......hmgggggogggggnh..........',
      '.......hmgggooWoogggnh..........',
      '.......hmgLUUUUUUULgnh..........',
      '.......hgsLvVQVVVVLsnh..........',
      '.......hgtLVVVVVVVLtnh..........',
      '.......hgLuuuuuuuuuLnh..........',
      '........LvvvvvvvvvvvL...........',
      '........aDCAhhhhhaDCA...........',
      '........AAAA.....AAAA...........',
    ],
    // Closed lids laid over the open eyes for the blink.
    shut: {
      top: 17,
      rows: [
        '.......sssss.....sssss..........',
        '........eeee.....eeee...........',
      ],
    },
    // The screen edge pixel where the text cursor blinks.
    cursor: [16, 25],
  },
  // Favicon cut: same character redrawn for 16px, not a downscale.
  16: {
    grid: [
      'zzz.............',
      '..z....AAAA.....',
      '.z...aDECCAA....',
      'zzz.aDECCCCCA...',
      '...aDCCCCCCaAhh.',
      '..hyyYYYYYYYhQPh',
      '.hhGHhhhhhhhJPph',
      '.hhhsshhsshhJhh.',
      '.JheeesseeehJ...',
      '.JssQhssQhssJ...',
      '.JsrssssssrsJ...',
      '..TtsssTsstT....',
      '..hmggggggnh....',
      '..hgLUUUULnh....',
      '..hgLVQVVLnh....',
      '..hLvvvvvvLh....',
    ],
  },
};

// Cozy-wabi tokens, warmed for the sprite. Outlines are darker shades of each fill, lighter where
// light hits. Cap: A a C D E. Cuff: Y y G. Pompom: P p Q. Hair and its outline: J h H j.
// Skin: T s t r. Eyes: e (lids), h (iris), Q (glint). Moss hoodie: h g m n.
// Laptop: L outline, V lid back, v base edge, u hinge.
// Screen glow, a few cool pixels against the warm palette: W and o spill over the lid, c lights the
// cheeks and the brim's underside, u the chin, V the hair tips. U is the screen peeking over the lid.
const LIGHT = {
  z: '#694b36',
  A: '#6a2b1c', a: '#93492d', C: '#c4673f', D: '#e08a5c', E: '#f8c08f',
  Y: '#f0c477', y: '#fbe3a6', G: '#d39155',
  P: '#f2eadb', p: '#d6c5a7', Q: '#fffaf0',
  J: '#3e2419', h: '#6b4532', H: '#8f5e3d', j: '#4a2c20',
  T: '#a85d43', s: '#fbd9b8', t: '#eab18c', r: '#f0907a', e: '#3e2419',
  g: '#69755a', n: '#465243', m: '#8e9b78',
  L: '#3f4652', v: '#7c8a99', V: '#5f6b7b', u: '#a7b4c2',
  U: '#3d5f8f', W: '#e6f6ff', o: '#bcd6dc', c: '#e2dbe8',
};
const CURSOR = '#ffffff';
// On dark grounds the hair and hoodie edge lift so the silhouette holds, and the z turns butter.
const DARK = { z: '#f0c477', J: '#64392a', h: '#84563b', H: '#ab744c', j: '#5e3a29' };
// Any paint order gives the same pixels; this one, found by search, keeps the paths shortest.
const BODY = [...'JChAaDEYyPpHGjeTtsrgnmLvVQuUoWc'];
const DARK_KEYS = Object.keys(DARK);

// One stroked path per colour: 1px horizontal runs, each stretched over pixels painted later.
function runs(grid, keys, top = 0) {
  return keys.map((k, i) => {
    const later = (ch) => keys.indexOf(ch) >= i;
    let d = '';
    let px = 0;
    let py = 0;
    grid.forEach((row, y) => {
      for (let x = 0; x < row.length; x += 1) {
        if (row[x] !== k) continue;
        let w = 0;
        for (let j = x; later(row[j]); j += 1) if (row[j] === k) w = j - x + 1;
        d += (d ? `m${x - px} ${y + top - py}` : `M${x} ${y + top}.5`) + `h${w}`;
        px = x + w;
        py = y + top;
        x += w - 1;
      }
    });
    return [k, d];
  }).filter(([, d]) => d);
}

// The art never changes, so each size and tone is encoded once and shared across renders.
const cache = new Map();

function parts(size, tone) {
  const cut = size <= 20 ? 16 : 32;
  const id = `${cut}:${tone}`;
  if (!cache.has(id)) cache.set(id, encode(ART[cut], tone));
  return cache.get(id);
}

function encode(art, tone) {
  const palette = tone === 'dark' ? { ...LIGHT, ...DARK } : LIGHT;
  const auto = tone !== 'light' && tone !== 'dark';
  const paint = ([k, d]) => ({ k, d, stroke: palette[k], cls: auto && DARK[k] ? `cc-m${DARK_KEYS.indexOf(k)}` : undefined });
  return {
    box: art.grid.length,
    body: runs(art.grid, BODY).map(paint),
    shut: art.shut ? runs(art.shut.rows, BODY, art.shut.top).map(paint) : [],
    cursor: art.cursor && { d: `M${art.cursor[0]} ${art.cursor[1]}.5h1`, stroke: CURSOR },
    z: paint(runs(art.grid, ['z'])[0]),
    // Dark-scheme overrides for tone="auto", keyed by class so one sprite serves both surfaces.
    css: auto ? `@media(prefers-color-scheme:dark){${DARK_KEYS.map((k, i) => `.cc-m${i}{stroke:${DARK[k]}}`).join('')}}` : '',
  };
}

// Static markup for favicons and other derived icons.
export function mascotSvg({ size = 32, tone = 'auto' } = {}) {
  const p = parts(size, tone);
  const path = ({ d, stroke, cls }) => `<path${cls ? ` class="${cls}"` : ''} stroke="${stroke}" d="${d}"/>`;
  const style = p.css ? `<style>${p.css}</style>` : '';
  return `<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 ${p.box} ${p.box}" width="${size}" height="${size}" shape-rendering="crispEdges">${style}${p.body.map(path).join('')}${p.cursor ? path(p.cursor) : ''}${path(p.z)}</svg>`;
}

// Sleepy nightcap mascot holding a mug. `animated` adds a slow blink and drifting z;
// tone="auto" follows the colour scheme, "light" or "dark" pins a palette.
export default function CozyMascot({ size = 32, tone = 'auto', animated = false, className = '' }) {
  const p = parts(size, tone);
  const classes = ['cc-mascot', animated && 'cc-mascot--animated', className].filter(Boolean).join(' ');
  const path = ({ k, d, stroke, cls }) => <path key={k} className={cls} stroke={stroke} d={d} />;
  return (
    <svg className={classes} viewBox={`0 0 ${p.box} ${p.box}`} width={size} height={size} shapeRendering="crispEdges" aria-hidden="true" focusable="false">
      {p.css && <style>{p.css}</style>}
      {p.body.map(path)}
      {p.cursor && <path className="cc-mascot-cursor" stroke={p.cursor.stroke} d={p.cursor.d} />}
      {animated && p.shut.length > 0 && <g className="cc-mascot-blink">{p.shut.map(path)}</g>}
      <path className={['cc-mascot-z', p.z.cls].filter(Boolean).join(' ')} stroke={p.z.stroke} d={p.z.d} />
    </svg>
  );
}
