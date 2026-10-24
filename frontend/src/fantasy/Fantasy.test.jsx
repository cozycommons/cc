import React from 'react';
import { render, screen, fireEvent } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Fantasy from './Fantasy.jsx';

vi.mock('../api.js', () => ({ getUrl: () => 'https://api.example.test' }));

const snapshot = {
  version: 'public-v1', generated_at: '2026-10-24T15:00:00Z', captured_at: '2026-10-24T14:55:00Z', names: 'real',
  matchup: { id: 1, ends: '2026-10-25' }, label: 'Uncalibrated model estimates, not betting odds',
  matchups: [
    { home: { name: 'Blowout Home' }, away: { name: 'Blowout Away' }, scores: [300, 500], projected_totals: [800, 1200],
      chance: 4, range: [1, 8], margin_80: [-500, -200],
      days: [{ date: '2026-10-24', state: 'final', actual: [300, 500], expected: [320, 480], games: [5, 7] },
        { date: '2026-10-25', state: 'projected', actual: null, expected: [500, 700], games: [6, 8] }],
      odds_history: [] },
    { home: { name: 'Close Home' }, away: { name: 'Close Away' }, scores: [410, 400], projected_totals: [1000, 990],
      chance: 52, range: [45, 58], margin_80: [-80, 100],
      days: [{ date: '2026-10-24', state: 'final', actual: [410, 400], expected: [400, 400], games: [6, 6] },
        { date: '2026-10-25', state: 'projected', actual: null, expected: [590, 590], games: [6, 6] }],
      odds_history: [{ date: '2026-10-23', chance: 47 }, { date: '2026-10-24', chance: 52 }] },
    { home: { name: 'Broken Home' }, away: { name: 'Broken Away' }, unavailable: true },
  ],
};

const reply = (status, body) => ({ status, ok: status < 400, json: async () => body });
const respond = (status, body) => vi.fn().mockResolvedValue(reply(status, body));
const view = () => render(<MemoryRouter><Fantasy /></MemoryRouter>);

describe('Fantasy predictions page', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('lists the closest race first with win chances and a by-day table', async () => {
    vi.stubGlobal('fetch', respond(200, snapshot));
    view();
    const names = (await screen.findAllByText(/ (Home|Away)$/)).map(node => node.textContent);
    expect(names.slice(0, 2)).toEqual(['Close Home', 'Close Away']);
    expect(screen.getByText('96%')).toBeTruthy();
    expect(screen.getByText('Not available')).toBeTruthy();
    expect(screen.getByText('+5 since Fri')).toBeTruthy();
    fireEvent.click(screen.getAllByRole('button', { name: /^By day: Close Home vs Close Away/ })[0]);
    expect(screen.getByRole('table')).toBeTruthy();
    expect(fetch).toHaveBeenCalledWith('https://api.example.test/espn/public/predictions/latest', expect.anything());
    expect(fetch).toHaveBeenCalledTimes(1);
  });

  it('falls back to the interim snapshot when the API has none', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(reply(404, null)).mockResolvedValueOnce(reply(200, snapshot)));
    view();
    expect(await screen.findByText('Close Home')).toBeTruthy();
    expect(fetch.mock.calls[1][0]).toContain('gist.githubusercontent.com');
  });

  it('ignores a fallback response that is not a public snapshot', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValueOnce(reply(404, null)).mockResolvedValueOnce(reply(200, { players: [] })));
    view();
    expect(await screen.findByText('No predictions yet.')).toBeTruthy();
  });

  it('shows an empty state when nothing has been published', async () => {
    vi.stubGlobal('fetch', respond(404, null));
    view();
    expect(await screen.findByText('No predictions yet.')).toBeTruthy();
  });

  it('reports a failed request', async () => {
    vi.stubGlobal('fetch', respond(500, null));
    view();
    expect(await screen.findByRole('alert')).toBeTruthy();
  });
});
