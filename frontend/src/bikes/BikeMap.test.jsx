import React from 'react';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import BikeMap, { project, unproject } from './BikeMap.jsx';

vi.mock('../api.js', () => ({ getUrl: () => 'https://api.example.test' }));

const HOME = { lat: 40.7497, lng: -73.9915 };
const STATIONS = {
  id: ['a', 'b'], name: ['W 31 St & 7 Ave', 'W 37 St & Broadway'],
  lat: [40.7497, 40.7546], lng: [-73.9915, -73.9876],
  bikes: [5, 0], ebikes: [2, 0], docks: [10, 9], flags: [3, 3],
};
const dotX = (name) => Number(screen.getByText(name, { selector: '.bk-dot text' }).getAttribute('x'));

function setup(props = {}) {
  const onPlan = vi.fn();
  const utils = render(<BikeMap stations={STATIONS} need="bike" home={HOME} highlight={['a', 'b']} onPlan={onPlan} {...props} />);
  const svg = screen.getByRole('img', { name: /^Map of Citi Bike stations/ });
  // jsdom has no layout: the map is 360 x 420 CSS pixels, one per drawing unit.
  svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: 360, height: 420, right: 360, bottom: 420 });
  return { ...utils, svg, onPlan };
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

  it('opens a station on tap, with odds and plan actions', async () => {
    const { svg, onPlan } = setup();
    const [x, y] = project({ ...HOME, r: 700 }, STATIONS.lng[1], STATIONS.lat[1]);
    pointer(svg, 'pointerDown', x, y);
    pointer(svg, 'pointerUp', x, y);
    expect(await screen.findByRole('dialog', { name: 'W 37 St & Broadway' })).toBeTruthy();
    expect(await screen.findByText('90%')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Plan to here' }));
    expect(onPlan).toHaveBeenCalledWith('to', { name: 'W 37 St & Broadway', lat: 40.7546, lng: -73.9876 });
  });

  it('flies to a searched station and opens it', async () => {
    setup();
    fireEvent.change(screen.getByLabelText('Find a station on the map'), { target: { value: 'west 31st' } });
    fireEvent.click(screen.getByRole('button', { name: 'W 31 St & 7 Ave' }));
    expect(await screen.findByRole('dialog', { name: 'W 31 St & 7 Ave' })).toBeTruthy();
    expect(dotX('5')).toBeCloseTo(180, 0); // centered
  });

  it('opens on a shared view with its station', async () => {
    setup({ focus: { lat: 40.7546, lng: -73.9876, radius: 400, station: 'b' } });
    expect(await screen.findByRole('dialog', { name: 'W 37 St & Broadway' })).toBeTruthy();
  });
});
