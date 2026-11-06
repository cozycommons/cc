import React from 'react';
import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import BikesApp from './BikesApp.jsx';

vi.mock('../api.js', () => ({ getUrl: () => 'https://api.example.test' }));

const view = () => render(<MemoryRouter initialEntries={['/bikes']}><BikesApp /></MemoryRouter>);

function locate(coords) {
  vi.stubGlobal('navigator', { geolocation: { getCurrentPosition: (ok, fail) => (coords ? ok({ coords }) : fail()) } });
}

const LIVE = {
  age_s: 12,
  stations: {
    id: ['6331.01', '6364.07'], name: ['W 31 St & 7 Ave', 'W 37 St & Broadway'],
    lat: [40.74916, 40.7546], lng: [-73.9916, -73.9876],
    bikes: [0, 6], ebikes: [0, 4], docks: [40, 2], flags: [3, 3],
  },
};
const station = (over) => ({
  station: 'W 31 St & 7 Ave', station_id: '6331.01', walk_min: 1, bikes: 0, ebikes: 0, open_docks: 40,
  status: 'empty', chance: 0.2, wait_min: 8, expected_min: 7.4, ...over,
});
const WAIT = {
  need: 'bike', live: true,
  message: 'Walk to W 37 St & Broadway, a 7-minute walk: 6 bikes now. The nearest, W 31 St & 7 Ave, is empty: about 7 minutes expected.',
  stations: [station(), station({ station: 'W 37 St & Broadway', station_id: '6364.07', walk_min: 7, bikes: 6, ebikes: 4,
    open_docks: 2, status: 'available', chance: 0.97, wait_min: 12, expected_min: 7.3 })],
};
WAIT.best = WAIT.stations[1];
const PLAN = {
  live: true, walk_only_min: 38.2,
  message: 'Walk 7 minutes to W 37 St & Broadway, ride 12 minutes to Washington Pl & Greene St, then walk 2 minutes. About 21 minutes; walking is about 38 minutes.',
  best: {
    start: station({ station: 'W 37 St & Broadway', station_id: '6364.07', walk_min: 7, bikes: 6, ebikes: 4, chance: 0.97 }),
    end: station({ station: 'Washington Pl & Greene St', station_id: '5492.05', walk_min: 2, open_docks: 9, chance: 0.81 }),
    ride_min: 12, expected_min: 21.4,
  },
  alternatives: [],
};

function api() {
  const calls = [];
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    calls.push(url);
    const path = new URL(url).pathname;
    const body = { '/bikes/live': LIVE, '/bikes/wait': WAIT, '/bikes/plan': PLAN }[path];
    return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 404, json: async () => ({}) };
  }));
  return calls;
}

describe('Cozy Bikes', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('finds stations near you, ranks them, and asks again for docks', async () => {
    const calls = api();
    locate({ latitude: 40.750212, longitude: -73.991612 });
    view();
    fireEvent.click(screen.getByRole('button', { name: 'Use my location' }));
    expect(await screen.findByText(WAIT.message)).toBeTruthy();
    expect(calls).toContain('https://api.example.test/bikes/wait?lat=40.75021&lng=-73.99161&need=bike&limit=5');
    const cards = screen.getAllByRole('listitem').filter((li) => li.classList.contains('bk-station'));
    expect(cards.map((c) => within(c).getByRole('heading').textContent)).toEqual(['W 31 St & 7 Ave', 'W 37 St & Broadway']);
    expect(within(cards[1]).getByText('Best · Available')).toBeTruthy();
    expect(within(cards[1]).getByText('97%')).toBeTruthy();
    expect(screen.getByRole('img', { name: '2 stations within 800 m, colored by bikes' })).toBeTruthy();

    fireEvent.click(screen.getByRole('tab', { name: 'Dock' }));
    await waitFor(() => expect(calls).toContain('https://api.example.test/bikes/wait?lat=40.75021&lng=-73.99161&need=dock&limit=5'));
  });

  it('plans a trip from your location to a searched station', async () => {
    const calls = api();
    locate({ latitude: 40.750212, longitude: -73.991612 });
    view();
    fireEvent.click(screen.getByRole('tab', { name: 'Plan' }));
    fireEvent.click(screen.getByRole('button', { name: 'Start from my location' }));
    fireEvent.change(await screen.findByLabelText('To'), { target: { value: '37 broad' } });
    fireEvent.click(await screen.findByRole('button', { name: 'W 37 St & Broadway' }));
    expect(await screen.findByText(PLAN.message)).toBeTruthy();
    expect(calls.some((u) => u.startsWith('https://api.example.test/bikes/plan?from_lat=40.75021&from_lng=-73.99161&to_lat=40.7546&to_lng=-73.9876'))).toBe(true);
    expect(screen.getByText('6 bikes now · 97% likely on arrival')).toBeTruthy();
    expect(screen.getByText('9 docks now · 81% likely on arrival')).toBeTruthy();
  });

  it('explains a blocked location', async () => {
    api();
    locate(null);
    view();
    fireEvent.click(screen.getByRole('button', { name: 'Use my location' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Allow location to find stations near you.');
  });
});
