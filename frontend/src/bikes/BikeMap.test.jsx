import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import BikeMap, { fitView, project, unproject } from './BikeMap.jsx';

vi.mock('../api.js', () => ({ getUrl: () => 'https://api.example.test' }));

const HOME = { lat: 40.7497, lng: -73.9915 };
const STATIONS = {
  id: ['a', 'b'], name: ['W 31 St & 7 Ave', 'W 37 St & Broadway'],
  lat: [40.7497, 40.7546], lng: [-73.9915, -73.9876],
  bikes: [5, 0], ebikes: [2, 0], docks: [10, 9], flags: [3, 3],
};
const dotX = (name) => Number(screen.getByText(name, { selector: '.bk-dot text' }).getAttribute('x'));

function setup(props = {}) {
  const utils = render(<BikeMap stations={STATIONS} need="bike" home={HOME} you={HOME} highlight={['a', 'b']} {...props} />);
  const svg = screen.getByRole('img', { name: /^Map of Citi Bike stations/ });
  // jsdom has no layout: the map is 360 x 420 CSS pixels, one per drawing unit.
  svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: 360, height: 420, right: 360, bottom: 420 });
  return { ...utils, svg };
}
const pointer = (svg, type, x, y, id = 1) => fireEvent[type](svg, { pointerId: id, clientX: x, clientY: y });

describe('interactive map', () => {
  beforeEach(() => {
    vi.stubGlobal('fetch', vi.fn(async (url) => (String(url).includes('/bikes/stations/')
      ? { ok: true, status: 200, json: async () => ({ chance: { bike: { '15_min': 0.9, '30_min': 0.8 } } }) }
      : { ok: false, status: 404, json: async () => ({}) })));
  });
  afterEach(() => vi.unstubAllGlobals());

  it('projects and unprojects round trip', () => {
    const view = { lat: 40.75, lng: -73.99, r: 700 };
    const [x, y] = project(view, -73.98, 40.76);
    const back = unproject(view, x, y);
    expect(back.lat).toBeCloseTo(40.76, 9);
    expect(back.lng).toBeCloseTo(-73.98, 9);
  });

  it('fits points between the floating controls and the sheet', () => {
    const points = [{ lat: 40.74, lng: -73.99 }, { lat: 40.75, lng: -73.98 }];
    const view = { ...fitView(points, 390, 700, { top: 120, bottom: 0.4 }), w: 390, h: 700 };
    for (const p of points) {
      const [x, y] = project(view, p.lng, p.lat);
      expect(x).toBeGreaterThan(0);
      expect(x).toBeLessThan(390);
      expect(y).toBeGreaterThan(120);       // below the search bar
      expect(y).toBeLessThan(700 * 0.6);    // above the sheet
    }
    // On a wide screen the list is a column on the left.
    const wide = { ...fitView(points, 1280, 800, { top: 16, left: 432 }), w: 1280, h: 800 };
    for (const p of points) expect(project(wide, p.lng, p.lat)[0]).toBeGreaterThan(432);
  });

  it('pans with a drag and zooms with the buttons', async () => {
    const { svg } = setup();
    const before = dotX('5');
    pointer(svg, 'pointerDown', 100, 100);
    pointer(svg, 'pointerMove', 160, 100);
    pointer(svg, 'pointerUp', 160, 100);
    await waitFor(() => expect(dotX('5')).toBeCloseTo(before + 60, 0));
    const centerBefore = dotX('5');
    fireEvent.click(screen.getByRole('button', { name: 'Zoom in' }));
    // Zooming about the center moves every point away from it by 1.5x.
    await waitFor(() => expect(dotX('5') - 180).toBeCloseTo((centerBefore - 180) * 1.5, 0));
  });

  it('selects a tapped station, and offers to check from a tapped spot', async () => {
    const onSelect = vi.fn();
    const onPin = vi.fn();
    const { svg } = setup({ onSelect, onPin });
    const [x, y] = project({ ...HOME, r: 700 }, STATIONS.lng[1], STATIONS.lat[1]);
    pointer(svg, 'pointerDown', x, y);
    pointer(svg, 'pointerUp', x, y);
    expect(onSelect).toHaveBeenCalledWith('b');
    pointer(svg, 'pointerDown', 40, 380);
    pointer(svg, 'pointerUp', 40, 380);
    fireEvent.click(await screen.findByRole('button', { name: 'Check from here' }));
    const spot = unproject({ ...HOME, r: 700 }, 40, 380);
    expect(onPin).toHaveBeenCalledWith({ lat: Number(spot.lat.toFixed(5)), lng: Number(spot.lng.toFixed(5)) });
  });

  it('opens on a shared view', async () => {
    setup({ focus: { lat: 40.7546, lng: -73.9876, radius: 400, station: 'b' }, selected: 'b' });
    expect(document.querySelector('.bk-dot.is-selected')).toBeTruthy();
  });
});
