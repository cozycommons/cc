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
    bikes: [0, 6], ebikes: [0, 4], docks: [40, 2], flags: [3, 3 | 4],
  },
};
const station = (over) => ({
  station: 'W 31 St & 7 Ave', station_id: '6331.01', walk_min: 1, bikes: 0, ebikes: 0, open_docks: 40,
  status: 'empty', chance: 0.2, wait_min: 8, expected_min: 7.4, reported_s: 140, docks_disabled: 0,
  verdict: { tone: 'skip', text: 'Empty: a bike in about 8 minutes' }, lat: 40.74916, lng: -73.9916, ...over,
});
const WAIT = {
  need: 'bike', live: true, feed_updated_at: new Date(Date.now() - 30000).toISOString(), age_s: 10,
  message: 'Walk to W 37 St & Broadway, a 7-minute walk: 6 bikes now. The nearest, W 31 St & 7 Ave, is empty: about 7 minutes expected.',
  stations: [station(), station({ station: 'W 37 St & Broadway', station_id: '6364.07', walk_min: 7, bikes: 6, ebikes: 4,
    open_docks: 2, status: 'available', chance: 0.97, wait_min: 12, expected_min: 7.3, lat: 40.7546, lng: -73.9876,
    verdict: { tone: 'go', text: 'Go: it will be there' } })],
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

// A search result's button. (findByRole with a name is very slow on this page.)
const result = async (name) => (await screen.findByText(name, { selector: '.bk-search__results span' })).closest('button');

const HERE = station({ station: 'W 37 St & Broadway', station_id: '6364.07', how: 'here', travel_min: 0, walk_back_min: 0,
  wait_min: 13, expected_min: 13, chance: 0, lat: 40.7546, lng: -73.9876 });
const OPTIONS = {
  need: 'bike',
  station: HERE,
  options: [
    HERE,
    station({ how: 'walk', travel_min: 3.5, walk_back_min: 0, bikes: 6, ebikes: 4, status: 'available', chance: 0.83,
      wait_min: 17, expected_min: 6.4, verdict: { tone: 'likely', text: 'Likely there when you arrive' } }),
  ],
  message: 'Walk 4 minutes to W 31 St & 7 Ave: 6 bikes there now, about 8 in 10 one is left. About 6 minutes in all. Waiting here is about 13 minutes.',
};
OPTIONS.best = OPTIONS.options[1];

const PLACES = { places: [{ label: '350 5th Avenue', area: 'Manhattan', kind: 'address', lat: 40.74844, lng: -73.98566 }] };

function api() {
  const calls = [];
  vi.stubGlobal('fetch', vi.fn(async (url) => {
    calls.push(url);
    const path = new URL(url).pathname;
    const body = { '/bikes/live': LIVE, '/bikes/wait': WAIT, '/bikes/plan': PLAN, '/bikes/places': PLACES,
      '/bikes/options': { ...OPTIONS, answer: OPTIONS.message } }[path];
    return body ? { ok: true, status: 200, json: async () => body } : { ok: false, status: 404, json: async () => ({}) };
  }));
  return calls;
}

describe('Cozy Bikes', () => {
  afterEach(() => { vi.unstubAllGlobals(); window.localStorage.clear(); });

  it('starts in the mode you picked last, and one tap on the start screen picks a mode and locates', async () => {
    const calls = api();
    window.localStorage.setItem('cozy-bikes.need', 'dock');
    locate({ latitude: 40.750212, longitude: -73.991612 });
    view();
    expect(screen.getByRole('radio', { name: 'Find a dock' }).getAttribute('aria-checked')).toBe('true');
    fireEvent.click(screen.getByRole('radio', { name: 'Find a bike' }));
    await waitFor(() => expect(calls).toContain('https://api.example.test/bikes/wait?lat=40.75021&lng=-73.99161&need=bike&limit=5'));
    expect(window.localStorage.getItem('cozy-bikes.need')).toBe('bike');
    fireEvent.click(await screen.findByRole('checkbox', { name: 'E-bikes only' }));
    await waitFor(() => expect(calls).toContain('https://api.example.test/bikes/wait?lat=40.75021&lng=-73.99161&need=ebike&limit=5'));
  });

  it('finds stations near you, ranks them, and asks again for docks', async () => {
    const calls = api();
    locate({ latitude: 40.750212, longitude: -73.991612 });
    view();
    fireEvent.click(screen.getByRole('radio', { name: 'Find a bike' }));
    expect(await screen.findByText(WAIT.message)).toBeTruthy();
    expect(calls).toContain('https://api.example.test/bikes/wait?lat=40.75021&lng=-73.99161&need=bike&limit=5');
    const cards = screen.getAllByRole('listitem').filter((li) => li.classList.contains('bk-station'));
    expect(cards.map((c) => within(c).getByRole('heading').textContent)).toEqual(['W 31 St & 7 Ave', 'Best · W 37 St & Broadway']);
    expect(within(cards[1]).getByText('Best ·')).toBeTruthy();
    // A verdict first, then the data behind it, in words rather than percents.
    expect(within(cards[1]).getByText('Go: it will be there').className).toBe('bk-verdict bk-verdict--go');
    expect(within(cards[1]).getByText('7 min walk · 2 classic, 4 e-bikes, 2 docks')).toBeTruthy();
    expect(within(cards[0]).getByText('Empty: a bike in about 8 minutes')).toBeTruthy();
    expect(within(cards[0]).getByText('1 min walk · 0 classic, 0 e-bikes, 40 docks · about 2 in 10 it refills in time')).toBeTruthy();
    expect(document.querySelectorAll('.bk-local__unknown')).toHaveLength(1);  // the stale one, drawn hollow
    expect(screen.getByRole('img', { name: /^Map of Citi Bike stations colored by bikes/ })).toBeTruthy();
    expect(within(cards[0]).getByText('Reported 2 min ago')).toBeTruthy();

    // Relocating asks again from the new position.
    locate({ latitude: 40.7359, longitude: -73.9911 });
    fireEvent.click(screen.getByRole('button', { name: 'Locate me' }));
    await waitFor(() => expect(calls).toContain('https://api.example.test/bikes/wait?lat=40.7359&lng=-73.9911&need=bike&limit=5'));

    expect(screen.getByRole('status').textContent).toMatch(/^Citi Bike data from \d+:\d\d [AP]M · checked just now/);

    // A failed refresh keeps the stations, dimmed, and says so.
    const working = globalThis.fetch;
    vi.stubGlobal('fetch', vi.fn(async () => ({ ok: false, status: 503, json: async () => ({ detail: 'Live Citi Bike dock data is unavailable.' }) })));
    fireEvent.click(screen.getByRole('button', { name: 'Refresh' }));
    expect(await screen.findByText(/^Couldn't refresh\. Showing Citi Bike data from/)).toBeTruthy();
    expect(document.querySelector('.bk-results.is-stale')).toBeTruthy();
    expect(screen.getByText(WAIT.message)).toBeTruthy();
    vi.stubGlobal('fetch', working);

    fireEvent.click(screen.getByRole('radio', { name: 'Find a dock' }));
    expect(document.querySelector('.bk-page').dataset.mode).toBe('dock');
    await waitFor(() => expect(calls).toContain('https://api.example.test/bikes/wait?lat=40.7359&lng=-73.9911&need=dock&limit=5'));
  });

  it('plans a trip from your location to a searched station', async () => {
    const calls = api();
    locate({ latitude: 40.750212, longitude: -73.991612 });
    view();
    fireEvent.click(screen.getByRole('tab', { name: 'Plan' }));
    fireEvent.click(screen.getByRole('button', { name: 'Use my location' }));
    fireEvent.change(await screen.findByLabelText('To'), { target: { value: '37 broad' } });
    fireEvent.click(await result('W 37 St & Broadway'));
    expect(await screen.findByText(PLAN.message)).toBeTruthy();
    expect(calls.some((u) => u.startsWith('https://api.example.test/bikes/plan?from_lat=40.75021&from_lng=-73.99161&to_lat=40.7546&to_lng=-73.9876'))).toBe(true);
    expect(screen.getByText('6 bikes now · odds on arrival very likely')).toBeTruthy();
    expect(screen.getByText('9 docks now · odds on arrival about 8 in 10')).toBeTruthy();
  });

  it('answers from a searched address without your location, and a tapped station asks wait or move on', async () => {
    const calls = api();
    view();
    fireEvent.change(screen.getByLabelText('Search an address, place or station'), { target: { value: '350 5th' } });
    fireEvent.click(await result('350 5th Avenue'));
    await waitFor(() => expect(calls).toContain('https://api.example.test/bikes/wait?lat=40.74844&lng=-73.98566&need=bike&limit=5'));
    expect(await screen.findByText('350 5th Avenue')).toBeTruthy();
    const svg = await screen.findByRole('img', { name: /^Map of Citi Bike stations/ });
    svg.getBoundingClientRect = () => ({ left: 0, top: 0, width: 360, height: 420, right: 360, bottom: 420 });
    const { project } = await import('./BikeMap.jsx');
    const [x, y] = project({ lat: 40.74844, lng: -73.98566, r: 700 }, -73.9876, 40.7546);
    fireEvent.pointerDown(svg, { pointerId: 1, clientX: x, clientY: y });
    fireEvent.pointerUp(svg, { pointerId: 1, clientX: x, clientY: y });
    // Tapping a station asks what to do standing there: wait, or walk on.
    await waitFor(() => expect(calls).toContain('https://api.example.test/bikes/options?station=6364.07&need=bike'));
    const sheet = await screen.findByRole('dialog');
    expect(await within(sheet).findByText('Walk to W 31 St & 7 Ave')).toBeTruthy();
    expect(within(sheet).getByText('Need a bike here?')).toBeTruthy();
    expect(within(sheet).getByText('About 6 min in all, vs about 13 min waiting here.')).toBeTruthy();
    const rows = sheet.querySelectorAll('.bk-option');
    expect([...rows].map((r) => r.textContent)).toEqual([
      'Wait here0 bikes now · next in about 13 min13 min',
      'W 31 St & 7 AveWalk 4 min · 6 bikes now · about 8 in 10 one is left6 min',
    ]);
    expect(rows[1].classList.contains('is-best')).toBe(true);
    fireEvent.click(within(sheet).getByText('Start from here'));
    await waitFor(() => expect(screen.queryByRole('dialog')).toBeNull());
    expect(screen.getByText('W 37 St & Broadway', { selector: '.bk-from b' })).toBeTruthy();
  });

  it('explains a blocked location', async () => {
    api();
    locate(null);
    view();
    fireEvent.click(screen.getByRole('radio', { name: 'Find a dock' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Allow location to find stations near you.');
  });
});

describe('station search', () => {
  it('folds street words like the API', async () => {
    const { matches, searchWords } = await import('./PlaceSearch.jsx');
    expect(searchWords('West 31st Street & 7th Avenue')).toEqual(['w', '31', 'st', '&', '7', 'ave']);
    expect(matches('W 31 St & 7 Ave', searchWords('west 31st 7th avenue'))).toBe(true);
    expect(matches('Henry Hudson Pkwy E & W 231 St', searchWords('31'))).toBe(false);
  });
});

describe('report age', () => {
  it('reads minutes, hours, then over a day', async () => {
    const { reportedLabel } = await import('./NearMe.jsx');
    expect([30, 140, 3 * 3600, 1783000000].map(reportedLabel)).toEqual(
      ['Reported just now', 'Reported 2 min ago', 'Reported 3 hours ago', 'No report in over a day']);
  });
});
