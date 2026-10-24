import React from 'react';
import { fireEvent, render, screen } from '@testing-library/react';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import { afterEach, describe, expect, it, vi } from 'vitest';
import Fantasy from './Fantasy.jsx';
import { SNAPSHOT_V2 } from './fixture.js';

vi.mock('../api.js', () => ({ getUrl: () => 'https://api.example.test' }));

const respond = (status, body) => vi.fn().mockResolvedValue({ status, ok: status < 400, json: async () => body });
const view = path => render(<MemoryRouter initialEntries={[path]}><Routes><Route path="/fantasy/*" element={<Fantasy />} /></Routes></MemoryRouter>);

describe('Fantasy pages', () => {
  afterEach(() => vi.unstubAllGlobals());

  it('hub shows the season race and links each matchup to its page', async () => {
    vi.stubGlobal('fetch', respond(200, structuredClone(SNAPSHOT_V2)));
    view('/fantasy');
    expect(await screen.findByText('Race to the playoffs')).toBeTruthy();
    expect(screen.getByText(/leads because/)).toBeTruthy();
    const link = screen.getByRole('link', { name: /Glass Cleaners vs Lob City/ });
    expect(link.getAttribute('href')).toBe('/fantasy/1-2');
  });

  it('race rows show playoff and title odds and expand into labelled finishes', async () => {
    vi.stubGlobal('fetch', respond(200, structuredClone(SNAPSHOT_V2)));
    view('/fantasy');
    const row = await screen.findByRole('button', { name: /^Glass Cleaners: \d+% playoffs, \d+% title$/ });
    expect(row.getAttribute('aria-expanded')).toBe('false');
    expect(document.querySelector('.fx-finish')).toBeNull();
    fireEvent.click(row);
    expect(row.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByRole('img', { name: /Glass Cleaners finish chances: 1st \d+%/ })).toBeTruthy();
    expect(document.querySelectorAll('.fx-finish-col').length).toBe(4);
  });

  it('phones get chart-free cards, labelled projections and a short playoff race', async () => {
    vi.stubGlobal('matchMedia', query => ({ matches: query === '(max-width: 600px)', addEventListener() {}, removeEventListener() {} }));
    vi.stubGlobal('fetch', respond(200, structuredClone(SNAPSHOT_V2)));
    view('/fantasy');
    await screen.findByText('Race to the playoffs');
    expect(document.querySelector('.fx-chart')).toBeNull();
    expect(screen.getAllByText(/^proj\. \d+$/).length).toBeGreaterThan(0);
    const raceRows = () => document.querySelectorAll('.fx-race-row:not(.fx-race-labels)').length;
    expect(raceRows()).toBe(2);
    fireEvent.click(screen.getByRole('button', { name: /Show all \d+ teams/ }));
    expect(raceRows()).toBeGreaterThan(2);
    expect(screen.queryByRole('button', { name: /Show all/ })).toBeNull();
  });

  it('matchup page shows the hero, daily bars and players who scored', async () => {
    vi.stubGlobal('fetch', respond(200, structuredClone(SNAPSHOT_V2)));
    view('/fantasy/1-2');
    expect(await screen.findByText('Points by day')).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2, name: 'Glass Cleaners' })).toBeTruthy();
    expect(screen.getByText(/Who scored ·/)).toBeTruthy();
    const firstDay = screen.getAllByRole('button', { pressed: false }).find(b => b.getAttribute('aria-label')?.includes('Oct 20'));
    fireEvent.click(firstDay);
    expect(screen.getByText(/Who scored · Tue, Oct 20/)).toBeTruthy();
    expect(document.querySelector('.fx-players li img').getAttribute('src')).toMatch(/a\.espncdn\.com\/i\/headshots\/nba\/players\/full\/\d+\.png/);
  });

  it('unknown matchup shows a way back', async () => {
    vi.stubGlobal('fetch', respond(200, structuredClone(SNAPSHOT_V2)));
    view('/fantasy/9-9');
    expect(await screen.findByText("This matchup isn't available.")).toBeTruthy();
    expect(screen.getByRole('link', { name: '← All matchups' })).toBeTruthy();
  });

  it('shows an empty state and errors', async () => {
    vi.stubGlobal('fetch', respond(404, null));
    view('/fantasy');
    expect(await screen.findByText('No predictions yet.')).toBeTruthy();
  });
});
