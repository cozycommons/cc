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
    expect(screen.getByText(/Most projected wins|Best playoff odds/)).toBeTruthy();
    const link = screen.getByRole('link', { name: /Glass Cleaners vs Lob City/ });
    expect(link.getAttribute('href')).toBe('/fantasy/1-2');
  });

  it('shows outperformers instead of filler text, with how each was acquired', async () => {
    const snap = structuredClone(SNAPSHOT_V2);
    const final = snap.matchups.find(x => !x.unavailable).days.find(d => d.state === 'final');
    Object.assign(final.players[0][0], { points: 90, expected: 30, acquired: { how: 'draft', round: 11, pick: 130 } });
    vi.stubGlobal('fetch', respond(200, snap));
    view('/fantasy');
    const section = await screen.findByRole('region', { name: 'Outperformers this week' });
    expect(section.querySelector('.fx-hl-how').textContent).toBe('Round 11 · pick 130');
    expect(section.querySelector('.fx-hl-num strong').textContent).toMatch(/^\+\d+$/);
    expect(document.querySelector('.fx-card-head').textContent).toBe('ScoreTo win');
    for (const filler of [/Just for fun/, /chance to win from here/, /Uncalibrated/, /Locked/, /Big favorites/, /unlock after week 1/, /Assumes today/]) {
      expect(screen.queryByText(filler)).toBeNull();
    }
  });

  it('never announces a 100% trend before the matchup is final', async () => {
    const snap = structuredClone(SNAPSHOT_V2);
    const m = snap.matchups.find(x => !x.unavailable && x.days.some(d => d.state === 'projected'));
    m.odds_history = [{ date: '2026-10-21', chance: 80 }, { date: '2026-10-22', chance: 100 }];
    vi.stubGlobal('fetch', respond(200, snap));
    view(`/fantasy/${m.home}-${m.away}`);
    expect((await screen.findByRole('img', { name: /^Home win chance/ })).getAttribute('aria-label')).toBe('Home win chance from 80% to >99%');
  });

  it('shows the form toggle only once a week is complete', async () => {
    vi.stubGlobal('fetch', respond(200, structuredClone(SNAPSHOT_V2)));
    const first = view('/fantasy');
    await screen.findByText('Race to the playoffs');
    expect(screen.queryByRole('group', { name: 'Form weighting' })).toBeNull();
    first.unmount();
    const active = structuredClone(SNAPSHOT_V2);
    active.season.form_active = true;
    vi.stubGlobal('fetch', respond(200, active));
    view('/fantasy');
    expect(await screen.findByRole('group', { name: 'Form weighting' })).toBeTruthy();
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
    const swings = screen.getByText('Who’s swinging it').closest('.fx-panel');
    expect(swings.querySelectorAll('.fx-swing--cold b').length).toBeGreaterThan(0);
    expect(swings.querySelector('.fx-swing--cold b').textContent).toMatch(/^−\d+$/);
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
