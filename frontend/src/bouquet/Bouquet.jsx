import React from 'react';
import './bouquet.css';

// A hand-drawn SVG bouquet that blooms in, flower by flower.
// Self-contained: no data, no backend — just a page to open and show someone.

const petalRing = (count, radius, rx, ry, fill, keyPrefix) =>
  Array.from({ length: count }, (_, i) => (
    <ellipse
      key={`${keyPrefix}-${i}`}
      cx="0"
      cy={-radius}
      rx={rx}
      ry={ry}
      fill={fill}
      transform={`rotate(${(360 / count) * i})`}
    />
  ));

// Positioning and bloom animation live on separate nested groups: a CSS
// `transform` animation overrides the SVG `transform` attribute on the same
// element, so putting both on one <g> discards the translate and collapses
// the flower to the SVG origin. Outer <g> positions, inner <g> animates.
function Positioned({ x, y, delay, children }) {
  return (
    <g transform={`translate(${x} ${y})`}>
      <g className="bq-bloom" style={{ '--d': `${delay}s` }}>
        {children}
      </g>
    </g>
  );
}

// Layered round flower (rose / peony): outer petals, inner petals, heart.
function RoundFlower({ x, y, r, outer, inner, heart, delay }) {
  return (
    <Positioned x={x} y={y} delay={delay}>
      {petalRing(8, r * 0.52, r * 0.36, r * 0.55, outer, 'o')}
      {petalRing(5, r * 0.3, r * 0.26, r * 0.38, inner, 'i')}
      <circle r={r * 0.2} fill={heart} />
      <path
        d={`M ${-r * 0.12} 0 A ${r * 0.12} ${r * 0.12} 0 1 1 ${r * 0.12} 0 A ${r * 0.07} ${r * 0.07} 0 1 0 ${-r * 0.12} 0`}
        fill="none"
        stroke={heart}
        strokeWidth={r * 0.05}
        opacity="0.55"
      />
    </Positioned>
  );
}

function Tulip({ x, y, r, fill, inner, delay }) {
  const w = r * 0.78;
  const top = -r * 1.05;
  const bottom = r * 0.55;
  return (
    <Positioned x={x} y={y} delay={delay}>
      <path
        d={`M ${-w} ${bottom} C ${-w * 1.05} ${top * 0.35} ${-w * 0.42} ${top} 0 ${top * 0.42}
            C ${w * 0.42} ${top} ${w * 1.05} ${top * 0.35} ${w} ${bottom}
            C ${w * 0.45} ${bottom + r * 0.28} ${-w * 0.45} ${bottom + r * 0.28} ${-w} ${bottom} Z`}
        fill={fill}
      />
      <path
        d={`M ${-w * 0.38} ${bottom} C ${-w * 0.3} ${top * 0.3} ${-w * 0.12} ${top * 0.75} 0 ${top * 0.42}
            C ${w * 0.12} ${top * 0.75} ${w * 0.3} ${top * 0.3} ${w * 0.38} ${bottom}`}
        fill="none"
        stroke={inner}
        strokeWidth={r * 0.07}
        opacity="0.6"
      />
    </Positioned>
  );
}

function Daisy({ x, y, r, delay }) {
  return (
    <Positioned x={x} y={y} delay={delay}>
      {petalRing(10, r * 0.55, r * 0.2, r * 0.5, '#fdfbf5', 'd')}
      <circle r={r * 0.3} fill="#f2b33d" />
      <circle r={r * 0.16} fill="#e09b26" />
    </Positioned>
  );
}

// Baby's breath: a spray of tiny blossoms on hair-thin stems.
function Breath({ x, y, delay }) {
  const puffs = [
    [0, 0], [-13, -9], [12, -12], [-6, -20], [8, -24], [-18, -24], [18, -3],
  ];
  return (
    <Positioned x={x} y={y} delay={delay}>
      {puffs.map(([dx, dy], i) => (
        <path key={`s-${i}`} d={`M 0 26 Q ${dx * 0.4} 8 ${dx} ${dy}`} fill="none" stroke="#7d9b6a" strokeWidth="1.4" />
      ))}
      {puffs.map(([dx, dy], i) => (
        <circle key={`p-${i}`} cx={dx} cy={dy} r={i % 2 ? 3.4 : 4.4} fill="#ffffff" stroke="#e8e2d2" strokeWidth="0.8" />
      ))}
    </Positioned>
  );
}

function Leaf({ x, y, rotate, scale = 1 }) {
  return (
    <path
      d="M 0 0 C 16 -6 30 -22 34 -42 C 16 -38 2 -24 0 0 Z"
      fill="#6f9a5b"
      transform={`translate(${x} ${y}) rotate(${rotate}) scale(${scale})`}
    />
  );
}

const STEMS = [
  'M 200 408 C 196 320 198 220 200 128',
  'M 200 408 C 188 330 160 250 138 168',
  'M 200 408 C 212 330 240 250 262 168',
  'M 200 408 C 180 320 130 260 104 224',
  'M 200 408 C 220 320 270 260 296 224',
  'M 200 408 C 194 310 176 190 168 100',
  'M 200 408 C 206 310 226 190 234 96',
  'M 200 408 C 186 330 148 220 122 128',
  'M 200 408 C 214 330 252 220 278 122',
];

export default function Bouquet() {
  return (
    <main className="bq-page">
      <span className="bq-petal bq-petal--1" aria-hidden="true" />
      <span className="bq-petal bq-petal--2" aria-hidden="true" />
      <span className="bq-petal bq-petal--3" aria-hidden="true" />
      <span className="bq-petal bq-petal--4" aria-hidden="true" />
      <span className="bq-petal bq-petal--5" aria-hidden="true" />

      <div className="bq-stage">
        <svg
          className="bq-svg"
          viewBox="0 0 400 540"
          role="img"
          aria-label="A bouquet of roses, tulips, daisies and baby's breath wrapped in paper"
        >
          <g className="bq-sway">
            {/* stems */}
            {STEMS.map((d, i) => (
              <path key={i} className="bq-stem" d={d} pathLength="1" style={{ '--d': `${0.15 + i * 0.08}s` }} />
            ))}

            {/* leaves */}
            <g className="bq-bloom" style={{ '--d': '0.9s' }}>
              <Leaf x={172} y={330} rotate={-58} />
              <Leaf x={228} y={318} rotate={122} />
              <Leaf x={188} y={262} rotate={-96} scale={0.8} />
              <Leaf x={214} y={252} rotate={160} scale={0.8} />
            </g>

            {/* baby's breath at the edges */}
            <Breath x={86} y={168} delay={1.5} />
            <Breath x={314} y={162} delay={1.65} />
            <Breath x={200} y={66} delay={1.8} />

            {/* flowers */}
            <Tulip x={168} y={102} r={30} fill="#b48ec7" inner="#8e6aa8" delay={0.75} />
            <Tulip x={234} y={98} r={30} fill="#e2687c" inner="#c04a5e" delay={0.9} />
            <Daisy x={120} y={126} r={24} delay={1.05} />
            <Daisy x={280} y={120} r={24} delay={1.15} />
            <RoundFlower x={104} y={222} r={34} outer="#f6c9d4" inner="#ef9fb6" heart="#dd6f92" delay={0.55} />
            <RoundFlower x={296} y={222} r={34} outer="#f6c9d4" inner="#ef9fb6" heart="#dd6f92" delay={0.65} />
            <RoundFlower x={138} y={166} r={38} outer="#f49db4" inner="#e87b9c" heart="#cf5279" delay={0.4} />
            <RoundFlower x={262} y={166} r={38} outer="#f8b26a" inner="#f09440" heart="#d97726" delay={0.48} />
            <RoundFlower x={200} y={128} r={46} outer="#ef8fab" inner="#e56b8f" heart="#c94f74" delay={0.25} />

            {/* paper wrap */}
            <g className="bq-bloom" style={{ '--d': '0.1s' }}>
              <path d="M 128 356 L 272 356 L 214 486 C 208 498 192 498 186 486 Z" fill="#e9dcc3" />
              <path d="M 128 356 L 200 392 L 186 486 C 192 498 208 498 214 486 L 200 392 Z" fill="#dfcdaa" opacity="0.65" />
              <path d="M 128 356 L 272 356 L 262 380 L 138 380 Z" fill="#f3ead6" />
              {/* ribbon */}
              <path d="M 200 402 l -26 -13 c -10 -5 -18 6 -11 13 l 14 12 Z" fill="#c94f74" />
              <path d="M 200 402 l 26 -13 c 10 -5 18 6 11 13 l -14 12 Z" fill="#c94f74" />
              <circle cx="200" cy="403" r="7" fill="#a93d5e" />
              <path d="M 196 410 l -5 26 M 204 410 l 5 26" stroke="#c94f74" strokeWidth="5" strokeLinecap="round" />
            </g>
          </g>
        </svg>
      </div>

      <header className="bq-words">
        <h1 className="bq-title">for Laura</h1>
        <p className="bq-sub">grown in code, so they never wilt</p>
      </header>
    </main>
  );
}
