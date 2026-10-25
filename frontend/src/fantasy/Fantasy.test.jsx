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
  afterEach(() => { localStorage.clear(); vi.unstubAllGlobals(); });

  it('hub shows the season race and links each matchup to its page', async () => {
    vi.stubGlobal('fetch', respond(200, structuredClone(SNAPSHOT_V2)));
    view('/fantasy');
    expect(await screen.findByText('Playoff race')).toBeTruthy();
    expect(screen.queryByText(/simulated seasons|Most projected wins|Best playoff odds/)).toBeNull();
    const link = screen.getByRole('link', { name: /Harbor Hoopers vs Lob City/ });
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
    expect(section.querySelector('.fx-hl-row > strong').textContent).toMatch(/^\+\d+$/);
    expect(section.querySelector('.fx-hl-pts').textContent).toMatch(/^\d+/);
    expect(section.querySelector('.fx-hl-main small').textContent).toContain('·');
    for (const filler of [/Matchup in ESPN/, /^Score$/, /^To win$/, /exp\./, /Up \d+/, /Down \d+/, /Projected to/, /since \w{3}$/, /Just for fun/, /chance to win from here/, /Uncalibrated/, /Locked/, /Big favorites/, /unlock after week 1/, /Assumes today/]) {
      expect(screen.queryByText(filler)).toBeNull();
    }
  });

  it('never announces a 100% trend before the matchup is final', async () => {
    const snap = structuredClone(SNAPSHOT_V2);
    const m = snap.matchups.find(x => !x.unavailable && x.days.some(d => d.state === 'projected'));
    m.odds_history = [{ date: '2026-10-21', chance: 80 }, { date: '2026-10-22', chance: 100 }];
    vi.stubGlobal('fetch', respond(200, snap));
    view(`/fantasy/${m.home}-${m.away}`);
    expect((await screen.findByRole('img', { name: /^Win odds since/ })).getAttribute('aria-label')).toBe('Win odds since Wed: >99% to <1%');
    const labels = [...document.querySelectorAll('.fx-win--big .fx-win-labels span')].map(span => span.textContent);
    expect(labels).toEqual(['>99%▲20%', '<1%▼20%']);
  });

  it('shows the form toggle only once a week is complete', async () => {
    vi.stubGlobal('fetch', respond(200, structuredClone(SNAPSHOT_V2)));
    const first = view('/fantasy');
    await screen.findByText('Playoff race');
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
    const row = await screen.findByRole('button', { name: /^Harbor Hoopers: \d+% playoffs, \d+% title$/ });
    expect(row.getAttribute('aria-expanded')).toBe('false');
    expect(document.querySelector('.fx-finish')).toBeNull();
    fireEvent.click(row);
    expect(row.getAttribute('aria-expanded')).toBe('true');
    expect(screen.getByRole('img', { name: /Harbor Hoopers finish chances: 1st \d+%/ })).toBeTruthy();
    expect(document.querySelectorAll('.fx-finish-col').length).toBe(4);
  });

  it('phones get chart-free cards, labelled projections and a short playoff race', async () => {
    vi.stubGlobal('matchMedia', query => ({ matches: query === '(max-width: 600px)', addEventListener() {}, removeEventListener() {} }));
    vi.stubGlobal('fetch', respond(200, structuredClone(SNAPSHOT_V2)));
    view('/fantasy');
    await screen.findByText('Playoff race');
    expect(document.querySelector('.fx-chart')).toBeNull();
    expect(screen.getAllByText(/^proj\. \d+$/).length).toBeGreaterThan(0);
    const raceRows = () => document.querySelectorAll('.fx-race-row:not(.fx-race-labels)').length;
    expect(raceRows()).toBe(2);
    fireEvent.click(screen.getByRole('button', { name: /Show all \d+ teams/ }));
    expect(raceRows()).toBeGreaterThan(2);
    expect(screen.queryByRole('button', { name: /Show all/ })).toBeNull();
  });

  it('is one scrolling page with no section tabs or lineup sign-in', async () => {
    vi.stubGlobal('matchMedia', query => ({ matches: query === '(max-width: 600px)', addEventListener() {}, removeEventListener() {} }));
    vi.stubGlobal('fetch', respond(200, structuredClone(SNAPSHOT_V2)));
    view('/fantasy');
    await screen.findByText('Playoff race');
    expect(screen.queryByRole('navigation', { name: 'Sections' })).toBeNull();
    expect(document.querySelector('input[type=password]')).toBeNull();
    expect(screen.queryByText(/Automatic lineups|ESPN password/)).toBeNull();
  });

  it('dates the page by when scores were captured', async () => {
    const snap = structuredClone(SNAPSHOT_V2);
    snap.captured_at = '2026-10-25T19:31:00Z';
    snap.generated_at = '2026-10-25T20:02:00Z';
    vi.stubGlobal('fetch', respond(200, snap));
    view('/fantasy');
    await screen.findByText('Playoff race');
    const stamp = new Date(snap.captured_at).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' });
    expect(screen.getByText(`Week ${snap.matchup.id} · Scores as of ${stamp}`)).toBeTruthy();
  });

  it('matchup page shows the hero, daily bars and players who scored', async () => {
    vi.stubGlobal('fetch', respond(200, structuredClone(SNAPSHOT_V2)));
    view('/fantasy/1-2');
    expect(await screen.findByText('Points by day')).toBeTruthy();
    expect(screen.getByRole('heading', { level: 2, name: 'Harbor Hoopers' })).toBeTruthy();
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

  it('renders saved predictions immediately while a new request is pending', async () => {
    localStorage.setItem('fantasy:last-good:v1:https://api.example.test', JSON.stringify(SNAPSHOT_V2));
    vi.stubGlobal('fetch', vi.fn(() => new Promise(() => {})));
    view('/fantasy');
    expect(screen.getByText('Playoff race')).toBeTruthy();
    expect(screen.queryByText('Loading…')).toBeNull();
  });
});
