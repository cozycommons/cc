import { useEffect, useState } from 'react';

// Static street tiles built by `python -m bikes.basemap` (see that module for the
// format). Same-origin files: the map never tells a third party where you are.
const BASE = '/bikes/map';
const cache = new Map();

function fetchJson(path) {
  if (!cache.has(path)) {
    cache.set(path, fetch(path).then((r) => (r.ok ? r.json() : null)).catch(() => null));
  }
  return cache.get(path);
}

export function tilesFor(index, south, west, north, east) {
  const [lat0, lng0] = index.origin;
  const [dLat, dLng] = index.tile;
  const have = new Set(index.tiles);
  const keys = [];
  for (let x = Math.floor((west - lng0) / dLng); x <= Math.floor((east - lng0) / dLng); x += 1) {
    for (let y = Math.floor((south - lat0) / dLat); y <= Math.floor((north - lat0) / dLat); y += 1) {
      if (have.has(`${x}_${y}`)) keys.push([x, y]);
    }
  }
  return keys;
}

// One encoded polyline ([x0, y0, dx1, dy1, ...] from the tile's corner) as [[lng, lat], ...].
export function decode(flat, ox, oy, quantum) {
  const points = [];
  let qx = 0, qy = 0;
  for (let i = 0; i < flat.length; i += 2) {
    qx = i ? qx + flat[i] : flat[i];
    qy = i ? qy + flat[i + 1] : flat[i + 1];
    points.push([ox + qx * quantum, oy + qy * quantum]);
  }
  return points;
}

// Polylines per layer as [[lng, lat], ...], for the tiles covering the box.
export function useBasemap(south, west, north, east) {
  const [layers, setLayers] = useState(null);
  const box = [south, west, north, east].map((v) => v.toFixed(3)).join(',');
  useEffect(() => {
    let live = true;
    (async () => {
      const index = await fetchJson(`${BASE}/index.json`);
      if (!index) return;
      const [s, w, n, e] = box.split(',').map(Number);
      const tiles = await Promise.all(tilesFor(index, s, w, n, e).map(async ([x, y]) => [x, y, await fetchJson(`${BASE}/${x}_${y}.json`)]));
      const out = { attribution: index.attribution };
      for (const [x, y, tile] of tiles) {
        if (!tile) continue;
        const ox = index.origin[1] + x * index.tile[1], oy = index.origin[0] + y * index.tile[0];
        for (const [layer, lines] of Object.entries(tile)) {
          const list = (out[layer] ??= []);
          for (const flat of lines) list.push(decode(flat, ox, oy, index.quantum));
        }
      }
      if (live) setLayers(out);
    })();
    return () => { live = false; };
  }, [box]);
  return layers;
}
