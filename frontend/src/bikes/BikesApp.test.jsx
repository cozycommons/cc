import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import BikesApp from './BikesApp.jsx';

vi.mock('../api.js', () => ({ getUrl: () => 'https://api.example.test' }));

const view = () => render(<MemoryRouter initialEntries={['/bikes']}><BikesApp /></MemoryRouter>);

function locate(coords) {
  vi.stubGlobal('navigator', { geolocation: { getCurrentPosition: (ok, fail) => (coords ? ok({ coords }) : fail()) } });
}

describe('wait or ride', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('asks the API with the current location and shows its answer', async () => {
    locate({ latitude: 40.750212, longitude: -73.991612 });
    const fetch = vi.fn(async () => ({ status: 200, ok: true, json: async () => ({
      decision: 'ride', station: 'W 33 St & 7 Ave', open_docks: 0, wait_min: 31.4,
      message: 'Ride to W 37 St & Broadway: 4 open, a 3-minute ride and a 10-minute walk back.',
      alternative: { station: 'W 37 St & Broadway', open_docks: 4, ride_min: 3.2, walk_min: 9.8 },
    }) }));
    vi.stubGlobal('fetch', fetch);
    view();
    fireEvent.click(screen.getByRole('button', { name: 'Check docks near me' }));
    expect(await screen.findByRole('heading', { name: 'Ride on' })).toBeTruthy();
    expect(fetch).toHaveBeenCalledWith('https://api.example.test/bikes/wait-or-ride?lat=40.75021&lng=-73.99161');
    expect(screen.getByText('31 min')).toBeTruthy();
    expect(screen.getByText('W 37 St & Broadway, 4 open, 13 min')).toBeTruthy();
  });

  it('explains a blocked location and an out-of-area position', async () => {
    locate(null);
    view();
    fireEvent.click(screen.getByRole('button', { name: 'Check docks near me' }));
    expect((await screen.findByRole('alert')).textContent).toBe('Allow location to check docks near you.');

    locate({ latitude: 51.5, longitude: -0.1 });
    vi.stubGlobal('fetch', vi.fn(async () => ({ status: 422, ok: false, json: async () => ({}) })));
    fireEvent.click(screen.getByRole('button', { name: 'Check docks near me' }));
    expect(await screen.findByText('No Citi Bike docks near you.')).toBeTruthy();
  });
});
